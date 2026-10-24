// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "argus_capture_op/operator_catalog.hpp"

// clang-format off: Keep standard headers before SDK headers for cpplint.
#include <span>
#include <string_view>
#include <utility>

#include <holoscan/authoring/register_operator.hpp>
#include <holoscan/core/parameter_schema.hpp>

#include "argus_capture_op/argus_capture_op.hpp"
// clang-format on

namespace holoscan::camera {

namespace {

using authoring::MaterializedParameters;
using authoring::OpaqueOperatorRef;

struct CaptureThunks final : authoring::ManualOperatorRegistrationThunks<ArgusCaptureOp> {
  static OpaqueOperatorRef add_to_graph(Graph& graph, std::string_view name,
                                        const MaterializedParameters* parameters) {
    if (parameters != nullptr &&
        (parameters->type() == nullptr ||
         parameters->type()->local_type_token !=
             param_type_descriptor<ArgusCaptureConfig>().local_type_token)) {
      throw RuntimeError{Error{ErrorCode::kInvalidArgument, "AUTHORING_PARAMETER_TYPE_MISMATCH"}};
    }
    const ArgusCaptureConfig defaults;
    const auto& values = parameters == nullptr
                             ? defaults
                             : *static_cast<const ArgusCaptureConfig*>(parameters->data());
    return make_operator_ref(graph.op<ArgusCaptureOp>(name, values));
  }

  static expected<OpaqueOperatorRef, Error> add_from_assignments(
      Graph& graph, std::string_view name,
      std::span<const authoring::ParameterAssignment> assignments) {
    auto values = authoring::materialize_parameters(param_type_descriptor<ArgusCaptureConfig>(),
                                                    param_schema_descriptor<ArgusCaptureConfig>(),
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
      .name = "holoscan.camera.ArgusCaptureOp",
      .param_type = &param_type_descriptor<ArgusCaptureConfig>(),
      .param_schema = param_schema_descriptor<ArgusCaptureConfig>(),
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

expected<void, Error> register_argus_operator_catalog() {
  static const auto status = authoring::authoring_registry().register_operator(make_row());
  return status;
}

}  // namespace holoscan::camera
