// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "v4l2_capture_op/operator_catalog.hpp"

// clang-format off: Keep standard headers before SDK headers for cpplint.
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <utility>

#include <holoscan/authoring/register_operator.hpp>
#include <holoscan/core/parameter_schema.hpp>

#include "v4l2_capture_op/v4l2_capture_op.hpp"
// clang-format on

namespace holoscan::camera {
namespace {

// These values describe constructor arguments, not live-updatable Operator parameters.
struct CaptureParameters {
  std::string device{"/dev/video0"};
  int width{640};
  int height{480};
  int fps{30};
  std::string frame_id{kDefaultCameraFrameId};
  MemoryKind memory_kind{MemoryKind::kHost};
};

// cpplint parses the enum initializer inside this schema macro as a namespace body.
HOLOSCAN_PARAM_SCHEMA(
    CaptureParameters, param_schema("holoscan.camera.V4l2CaptureOp.Constructor", 1),
    field<&CaptureParameters::device>("device").description("V4L2 device node path."),
    field<&CaptureParameters::width>("width")
        .range(1, std::numeric_limits<int>::max())
        .description("Even YUYV capture width in pixels."),
    field<&CaptureParameters::height>("height")
        .range(1, std::numeric_limits<int>::max())
        .description("Capture height in pixels."),
    field<&CaptureParameters::fps>("fps")
        .range(1, 1'000'000'000)
        .description("Requested frames per second."),
    field<&CaptureParameters::frame_id>("frame_id").description("Image coordinate frame name."),
    field<&CaptureParameters::memory_kind>("memory_kind")
        .enum_values({param_enum_value("host", MemoryKind::kHost),
                      param_enum_value("pinned", MemoryKind::kPinnedHost),
                      // NOLINTNEXTLINE(whitespace/indent_namespace)
                      param_enum_value("device", MemoryKind::kCudaDevice)})
        .description("Output tensor placement; device requires an explicit GPU binding."));

using authoring::MaterializedParameters;
using authoring::OpaqueOperatorRef;

struct CaptureThunks final : authoring::ManualOperatorRegistrationThunks<V4l2CaptureOp> {
  static OpaqueOperatorRef add_to_graph(Graph& graph, std::string_view name,
                                        const MaterializedParameters* parameters) {
    if (parameters != nullptr &&
        (parameters->type() == nullptr ||
         parameters->type()->local_type_token !=
             param_type_descriptor<CaptureParameters>().local_type_token)) {
      throw RuntimeError{Error{ErrorCode::kInvalidArgument, "AUTHORING_PARAMETER_TYPE_MISMATCH"}};
    }
    const CaptureParameters defaults;
    const auto& values = parameters == nullptr
                             ? defaults
                             : *static_cast<const CaptureParameters*>(parameters->data());
    // Graph wraps native constructor exceptions with its construction diagnostic.
    return make_operator_ref(graph.op<V4l2CaptureOp>(name, values.device, values.width,
                                                     values.height, values.fps, values.frame_id,
                                                     values.memory_kind));
  }

  static expected<OpaqueOperatorRef, Error> add_from_assignments(
      Graph& graph, std::string_view name,
      std::span<const authoring::ParameterAssignment> assignments) {
    auto values = authoring::materialize_parameters(param_type_descriptor<CaptureParameters>(),
                                                    param_schema_descriptor<CaptureParameters>(),
                                                    assignments);
    if (!values) return make_unexpected(std::move(values).error());
    return invoke_add([&] { return add_to_graph(graph, name, &*values); });
  }

  static void set_params(const OpaqueOperatorRef&, const MaterializedParameters&) {
    throw RuntimeError{
        Error{ErrorCode::kNotSupported, "AUTHORING_MANUAL_ROW_PARAMETERS_IMMUTABLE"}};
  }
};

authoring::RegisteredOperatorType make_row() {
  return authoring::RegisteredOperatorType{
      .name = "holoscan.camera.V4l2CaptureOp",
      .param_type = &param_type_descriptor<CaptureParameters>(),
      .param_schema = param_schema_descriptor<CaptureParameters>(),
      .parameter_introspection = authoring::OperatorParameterIntrospection::kConstructorReplay,
      .add_to_graph = &CaptureThunks::add_to_graph,
      .add_to_graph_from_assignments = &CaptureThunks::add_from_assignments,
      .set_params = &CaptureThunks::set_params,
      .port = &CaptureThunks::port,
      .ports = &CaptureThunks::ports,
      .region_add = &CaptureThunks::region_add,
      .partition_add = &CaptureThunks::partition_add,
      .lifecycle_before = &CaptureThunks::lifecycle_before,
      .lifecycle_allow_self_restart = &CaptureThunks::lifecycle_allow_self_restart,
      .lifecycle_allow_external_restart = &CaptureThunks::lifecycle_allow_external_restart,
      .lifecycle_allow_restart_request = &CaptureThunks::lifecycle_allow_restart_request,
  };
}

}  // namespace

expected<void, Error> register_v4l2_operator_catalog() {
  static const auto status = authoring::authoring_registry().register_operator(make_row());
  return status;
}

}  // namespace holoscan::camera
