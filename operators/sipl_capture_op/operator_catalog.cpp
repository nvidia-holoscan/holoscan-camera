// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sipl_capture_op/operator_catalog.hpp"

// clang-format off: Keep standard headers before SDK headers for cpplint.
#include <algorithm>
#include <array>
#include <cstdint>
#include <format>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <utility>

#include <holoscan/authoring/constructor_handle.hpp>
#include <holoscan/authoring/register_operator.hpp>
#include <holoscan/authoring/registry.hpp>
#include <holoscan/core/parameter_schema.hpp>

#include "sipl_capture_op/sipl_capture_op.hpp"
#include "sipl_capture_op/sipl_capture_service.hpp"
#include "sipl_capture_op/sipl_capture_service_handle.hpp"
// clang-format on

namespace holoscan::camera {

// SIPLCaptureOp's immutable constructor values. Its SIPLCaptureService is not a value: the row
// takes it as the `service` constructor handle.
struct SIPLCaptureConfig {
  std::uint32_t camera_index{0};
  MemoryKind memory_kind{MemoryKind::kCudaDevice};
};

// Describe the native constructor configuration without duplicating its defaults.
// These values are replayed on graph clones, not updated on a running capture session.
// cpplint parses the enum initializer inside this schema macro as a namespace body.
// NOLINTBEGIN(whitespace/indent_namespace)
HOLOSCAN_PARAM_SCHEMA(
    SIPLCaptureConfig, param_schema("holoscan.camera.SIPLCaptureOp.Constructor", 1),
    field<&SIPLCaptureConfig::camera_index>("camera_index")
        .description("Zero-based index of the camera within the service's configuration."),
    field<&SIPLCaptureConfig::memory_kind>("memory_kind")
        .enum_values({param_enum_value("host", MemoryKind::kHost),
                      param_enum_value("pinned", MemoryKind::kPinnedHost),
                      param_enum_value("device", MemoryKind::kCudaDevice)})
        .description("Output tensor placement; device requires an explicit GPU binding."));
// NOLINTEND

namespace {

using authoring::ConstructorHandleInput;
using authoring::MaterializedParameters;
using authoring::OpaqueOperatorRef;
using authoring::OperatorConstructionInputs;
using authoring::ParameterAssignment;
using authoring::ParameterValueKind;

constexpr std::string_view kCaptureName = "holoscan.camera.SIPLCaptureOp";
constexpr std::array<std::string_view, 1> kRequiredParameters{"camera_index"};

// The configuration the description placeholder names. Description only builds the operator,
// which opens no camera; a graph that ran it anyway would fail to find this configuration rather
// than open the first one the SIPL database lists, as an empty name would.
constexpr const char* kPlaceholderCameraConfig = "holoscan-camera-registry-placeholder";

struct CaptureThunks final : authoring::ManualOperatorRegistrationThunks<SIPLCaptureOp> {
  static OpaqueOperatorRef add(Graph& graph, std::string_view name,
                               std::shared_ptr<SIPLCaptureService> service,
                               const SIPLCaptureConfig& config) {
    return make_operator_ref(graph.op<SIPLCaptureOp>(name, std::move(service),
                                                     config.camera_index, config.memory_kind));
  }

  static expected<OpaqueOperatorRef, Error> add_from_inputs(
      Graph& graph, std::string_view name, const OperatorConstructionInputs& inputs) {
    auto service = inputs.require_shared("service", sipl_capture_service_handle_type());
    if (!service) return make_unexpected(std::move(service).error());
    // Python requires camera_index before calling; a C++ caller of the registry is held to the
    // same rule rather than silently capturing camera 0.
    const auto given = [](const ParameterAssignment& assignment) {
      return assignment.name == kRequiredParameters[0] &&
             assignment.value.kind != ParameterValueKind::kNone;
    };
    if (std::ranges::none_of(inputs.values, given)) {
      return make_unexpected(
          Error{ErrorCode::kInvalidArgument,
                std::format("HOLOSCAN_CAMERA_OPERATOR_PARAMETER_REQUIRED field_name={}",
                            kRequiredParameters[0])});
    }
    auto values = authoring::materialize_parameters(param_type_descriptor<SIPLCaptureConfig>(),
                                                    param_schema_descriptor<SIPLCaptureConfig>(),
                                                    inputs.values);
    if (!values) return make_unexpected(std::move(values).error());
    return invoke_add([&] {
      return add(graph, name, std::move(*service),
                 *static_cast<const SIPLCaptureConfig*>(values->data()));
    });
  }

  // Port discovery builds the row once, without a handle. The placeholder service opens no
  // camera: SIPLCaptureService initializes NvSIPL only when first asked about its cameras, which
  // neither construction nor compilation does.
  static expected<OpaqueOperatorRef, Error> add_for_description(Graph& graph,
                                                                std::string_view name) {
    return invoke_add([&] {
      return add(graph, name,
                 std::make_shared<SIPLCaptureService>(kPlaceholderCameraConfig, "", false),
                 SIPLCaptureConfig{});
    });
  }

  static void set_params(const OpaqueOperatorRef&, const MaterializedParameters&) {
    throw RuntimeError{
        Error{ErrorCode::kNotSupported, "AUTHORING_MANUAL_ROW_PARAMETERS_IMMUTABLE"}};
  }
};

// The service's handle type lives in this library, which owns SIPLCaptureService, so the table is
// built at run time rather than as a constant.
const authoring::RegisteredConstructorInputs& capture_inputs() {
  static const std::array handles{
      ConstructorHandleInput{
          .name = "service",
          .description = "The SIPL camera configuration, shared by the operators of its cameras.",
          .type = &sipl_capture_service_handle_type().descriptor(),
      },
  };
  static const authoring::RegisteredConstructorInputs inputs{
      .handles = handles,
      .add_to_graph_from_inputs = &CaptureThunks::add_from_inputs,
      .add_for_description = &CaptureThunks::add_for_description,
  };
  return inputs;
}

authoring::RegisteredOperatorType make_capture_row() {
  using Thunks = CaptureThunks;
  return authoring::RegisteredOperatorType{
      .name = kCaptureName,
      .param_type = &param_type_descriptor<SIPLCaptureConfig>(),
      .param_schema = param_schema_descriptor<SIPLCaptureConfig>(),
      .parameter_introspection = authoring::OperatorParameterIntrospection::kConstructorReplay,
      .required_parameters = kRequiredParameters,
      .add_to_graph = &Thunks::add_without_constructor_handles,
      .add_to_graph_from_assignments = &Thunks::reject_without_constructor_handles,
      .set_params = &Thunks::set_params,
      .port = &Thunks::port,
      .ports = &Thunks::ports,
      .region_add = &Thunks::region_add,
      .partition_add = &Thunks::partition_add,
      .lifecycle_before = &Thunks::lifecycle_before,
      .lifecycle_allow_self_restart = &Thunks::lifecycle_allow_self_restart,
      .lifecycle_allow_external_restart = &Thunks::lifecycle_allow_external_restart,
      .lifecycle_allow_restart_request = &Thunks::lifecycle_allow_restart_request,
      .constructor_inputs = &capture_inputs(),
  };
}

}  // namespace

expected<void, Error> register_sipl_operator_catalog() {
  static const expected<void, Error> status = []() -> expected<void, Error> {
    return authoring::authoring_registry().register_operator(make_capture_row());
  }();
  return status;
}

}  // namespace holoscan::camera
