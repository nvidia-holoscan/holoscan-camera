// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Unit tests for the authoring-registry rows of operator_catalog.hpp, through which the Python
// bindings construct the operators. No camera is opened: SIPLCaptureService initializes
// NvSIPL only when asked about its cameras, and holoscan::compile() runs no lifecycle stage.

#include <gtest/gtest.h>

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <holoscan/authoring/constructor_handle.hpp>
#include <holoscan/authoring/register_operator.hpp>
#include <holoscan/authoring/registry.hpp>
#include <holoscan/core/compile.hpp>
#include <holoscan/core/connection_options.hpp>
#include <holoscan/core/errors.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/expected.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/time/realtime_clock.hpp>

#include <sipl_capture_op/operator_catalog.hpp>
#include <sipl_capture_op/sipl_capture_op.hpp>
#include <sipl_capture_op/sipl_capture_service.hpp>
#include <sipl_capture_op/sipl_capture_service_handle.hpp>

namespace camera = holoscan::camera;

namespace {

using holoscan::authoring::ConstructorHandleAssignment;
using holoscan::authoring::OpaqueOperatorRef;
using holoscan::authoring::OperatorConstructionInputs;
using holoscan::authoring::ParameterAssignment;
using holoscan::authoring::ParameterValue;
using holoscan::authoring::RegisteredOperatorType;

constexpr std::string_view kCaptureRow = "holoscan.camera.SIPLCaptureOp";

const RegisteredOperatorType& row(std::string_view name) {
  const auto registered = camera::register_sipl_operator_catalog();
  EXPECT_TRUE(registered) << registered.error().message;
  auto found = holoscan::authoring::authoring_registry().operator_type(name);
  if (!found) {
    throw std::runtime_error(std::string{"registry row not found: "} + std::string{name});
  }
  return found->get();
}

std::shared_ptr<camera::SIPLCaptureService> test_service() {
  return std::make_shared<camera::SIPLCaptureService>("ov2311_raw", "", /*raw_output=*/true);
}

holoscan::authoring::ConstructorHandle service_handle(
    std::shared_ptr<camera::SIPLCaptureService> service) {
  auto handle = holoscan::authoring::ConstructorHandle::from_shared(
      camera::sipl_capture_service_handle_type(), std::move(service));
  EXPECT_TRUE(handle) << handle.error().message;
  return handle ? std::move(*handle) : holoscan::authoring::ConstructorHandle{};
}

// Adds a SIPLCaptureOp as Python's graph.op() does: the service as the row's `service`
// constructor handle, everything else as `values`.
holoscan::expected<holoscan::authoring::RegisteredOperatorAddition, holoscan::Error> add_capture(
    holoscan::Graph& graph, std::string_view name, std::shared_ptr<camera::SIPLCaptureService> service,
    std::span<const ParameterAssignment> values) {
  const std::array handles{ConstructorHandleAssignment{"service", service_handle(std::move(service))}};
  return holoscan::authoring::add_registered_operator(
      graph, row(kCaptureRow), name, OperatorConstructionInputs{.values = values, .handles = handles});
}

ParameterValue integer(std::int64_t value) { return ParameterValue::from(value); }

// The typed handle behind a registry-built SIPLCaptureOp, recovered as the row's own thunks do.
struct CaptureHandle : holoscan::authoring::ManualOperatorRegistrationThunks<camera::SIPLCaptureOp> {
  static holoscan::OperatorHandle<camera::SIPLCaptureOp> of(const OpaqueOperatorRef& op) {
    EXPECT_TRUE(holds_type(op));
    return typed_handle(op);
  }
};

class NullFrameSinkOp final : public holoscan::Operator<> {
 public:
  void setup(holoscan::OperatorSpec& spec) override { spec.input(input, "input").queue_depth(1U); }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract result;
    result.trigger(holoscan::OnEach{input});
    return result;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    auto sample = input.receive();
    if (!sample) {
      return holoscan::make_unexpected(std::move(sample).error());
    }
    return {};
  }

  holoscan::Input<holoscan::schema::ImageT> input;
};

}  // namespace

TEST(SIPLCaptureOpCatalogTest, RegistersTheCaptureRow) {
  const auto registered = camera::register_sipl_operator_catalog();
  ASSERT_TRUE(registered) << registered.error().message;
  // Repeated registration is a no-op that reports the same result.
  EXPECT_TRUE(camera::register_sipl_operator_catalog());
  EXPECT_TRUE(holoscan::authoring::authoring_registry().operator_type(kCaptureRow));
}

TEST(SIPLCaptureOpCatalogTest, CaptureDescriptionNeedsNoService) {
  // Registry discovery builds each row once to learn its ports, and skips a row that fails, so
  // the SIPLCaptureOp row must describe itself without a service.
  (void)row(kCaptureRow);
  const auto described = holoscan::authoring::authoring_registry().describe_operator(kCaptureRow);
  ASSERT_TRUE(described) << described.error().message;
  std::vector<std::string> names;
  for (const auto& port : described->ports) {
    names.push_back(port.name);
  }
  EXPECT_EQ(names, (std::vector<std::string>{"frame", "sensor_data"}));
  ASSERT_EQ(described->constructor_handles.size(), 1U);
  EXPECT_EQ(described->constructor_handles[0].name, "service");
  EXPECT_EQ(described->constructor_handles[0].type_name,
            "holoscan.camera.SIPLCaptureService");
  EXPECT_TRUE(described->constructor_handles[0].required);
}

TEST(SIPLCaptureOpCatalogTest, BuildsCaptureFromItsServiceAndAppliesMemoryKind) {
  holoscan::Graph graph{"sipl_capture_catalog_memory_kind"};

  const std::array<ParameterAssignment, 1> default_kind{{{"camera_index", integer(1)}}};
  auto device = add_capture(graph, "default", test_service(), default_kind);
  ASSERT_TRUE(device) << device.error().message;
  EXPECT_EQ(CaptureHandle::of(device->op)->memory_kind(), holoscan::MemoryKind::kCudaDevice);

  for (const auto& [name, kind] :
       std::array<std::pair<std::string_view, holoscan::MemoryKind>, 3>{{
           {"device", holoscan::MemoryKind::kCudaDevice},
           {"pinned", holoscan::MemoryKind::kPinnedHost},
           {"host", holoscan::MemoryKind::kHost},
       }}) {
    const std::array<ParameterAssignment, 2> assignments{{
        {"camera_index", integer(0)},
        {"memory_kind", ParameterValue::from(name)},
    }};
    auto added = add_capture(graph, name, test_service(), assignments);
    ASSERT_TRUE(added) << name << ": " << added.error().message;
    EXPECT_EQ(CaptureHandle::of(added->op)->memory_kind(), kind) << name;
  }

  // A placement can also be given by its MemoryKind value, as the typed stub allows.
  const std::array<ParameterAssignment, 2> by_value{{
      {"camera_index", integer(0)},
      {"memory_kind", integer(static_cast<std::int64_t>(holoscan::MemoryKind::kPinnedHost))},
  }};
  auto numbered = add_capture(graph, "by_value", test_service(), by_value);
  ASSERT_TRUE(numbered) << numbered.error().message;
  EXPECT_EQ(CaptureHandle::of(numbered->op)->memory_kind(), holoscan::MemoryKind::kPinnedHost);
}

TEST(SIPLCaptureOpCatalogTest, CamerasShareOneServiceThatTheGraphKeepsAlive) {
  std::weak_ptr<camera::SIPLCaptureService> released;
  {
    holoscan::Graph graph{"sipl_capture_catalog_shared_service"};
    {
      auto service = test_service();
      released = service;
      const std::array<ParameterAssignment, 1> first{{{"camera_index", integer(0)}}};
      const std::array<ParameterAssignment, 1> second{{{"camera_index", integer(1)}}};
      ASSERT_TRUE(add_capture(graph, "first", service, first));
      ASSERT_TRUE(add_capture(graph, "second", service, second));
    }
    // Only the Graph's declarations hold the service now.
    EXPECT_FALSE(released.expired());
  }
  EXPECT_TRUE(released.expired());
}

TEST(SIPLCaptureOpCatalogTest, RejectsInvalidParameters) {
  holoscan::Graph graph{"sipl_capture_catalog_rejected"};
  const auto service = test_service();

  const auto expect_rejected = [&](std::string_view name,
                                   std::span<const ParameterAssignment> assignments,
                                   std::string_view expected_error) {
    auto added = add_capture(graph, name, service, assignments);
    ASSERT_FALSE(added) << name;
    EXPECT_NE(added.error().message.find(expected_error), std::string::npos)
        << name << ": " << added.error().message;
  };

  expect_rejected("missing_index", {},
                  "HOLOSCAN_CAMERA_OPERATOR_PARAMETER_REQUIRED field_name=camera_index");

  // An explicit None is not a camera index.
  const std::array<ParameterAssignment, 1> none_index{{{"camera_index", ParameterValue::none()}}};
  expect_rejected("none_index", none_index,
                  "HOLOSCAN_CAMERA_OPERATOR_PARAMETER_REQUIRED field_name=camera_index");

  const std::array<ParameterAssignment, 1> negative_index{{{"camera_index", integer(-1)}}};
  expect_rejected("negative_index", negative_index,
                  "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=camera_index");

  // The placement names are V4L2's and Argus's: the old cuda_device spelling is refused, and so is
  // None, which no longer selects the default.
  const std::array<ParameterAssignment, 2> old_name{{
      {"camera_index", integer(0)},
      {"memory_kind", ParameterValue::from(std::string_view{"cuda_device"})},
  }};
  expect_rejected("old_name", old_name, "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=memory_kind");
  const std::array<ParameterAssignment, 2> none_kind{{
      {"camera_index", integer(0)},
      {"memory_kind", ParameterValue::none()},
  }};
  expect_rejected("none_kind", none_kind,
                  "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=memory_kind");
  const std::array<ParameterAssignment, 2> unlisted_number{{
      {"camera_index", integer(0)},
      {"memory_kind", integer(0)},
  }};
  expect_rejected("unlisted_number", unlisted_number, "category=not_allowed");

  const std::array<ParameterAssignment, 2> unknown{{
      {"camera_index", integer(0)},
      {"raw_output", ParameterValue::from(true)},
  }};
  expect_rejected("unknown", unknown, "AUTHORING_PARAMETER_UNKNOWN field_name=raw_output");

  // A rejected construction leaves the Graph unchanged, so the name can be used again.
  const std::array<ParameterAssignment, 1> valid{{{"camera_index", integer(0)}}};
  auto added = add_capture(graph, "unknown", service, valid);
  EXPECT_TRUE(added) << added.error().message;
}

TEST(SIPLCaptureOpCatalogTest, RequiresItsService) {
  holoscan::Graph graph{"sipl_capture_catalog_missing_service"};
  const std::array<ParameterAssignment, 1> values{{{"camera_index", integer(0)}}};
  auto added = holoscan::authoring::add_registered_operator(
      graph, row(kCaptureRow), "camera", OperatorConstructionInputs{.values = values});
  ASSERT_FALSE(added);
  EXPECT_NE(added.error().message.find("AUTHORING_CONSTRUCTOR_HANDLE_REQUIRED field=service"),
            std::string::npos)
      << added.error().message;
}

TEST(SIPLCaptureOpCatalogTest, RejectsTheValueOnlyRoutes) {
  // Key setup: the row's value-only routes, which cannot carry the service.
  const auto& capture = row(kCaptureRow);
  holoscan::Graph graph{"sipl_capture_catalog_value_only"};
  const std::array<ParameterAssignment, 1> values{{{"camera_index", integer(0)}}};

  // Key assertion: both refuse, naming the constructor-handle route.
  auto added = capture.add_to_graph_from_assignments(graph, "camera", values);
  ASSERT_FALSE(added);
  EXPECT_NE(added.error().message.find("AUTHORING_CONSTRUCTOR_HANDLE_ROUTE_REQUIRED"),
            std::string::npos)
      << added.error().message;
  try {
    (void)capture.add_to_graph(graph, "materialized", nullptr);
    ADD_FAILURE() << "add_to_graph built a SIPLCaptureOp without its service";
  } catch (const holoscan::RuntimeError& error) {
    EXPECT_NE(std::string{error.what()}.find("AUTHORING_CONSTRUCTOR_HANDLE_ROUTE_REQUIRED"),
              std::string::npos)
        << error.what();
  }
}

TEST(SIPLCaptureOpCatalogTest, AFailedAddHoldsNothing) {
  std::weak_ptr<camera::SIPLCaptureService> released;
  holoscan::Graph graph{"sipl_capture_catalog_failed_add"};
  {
    auto service = test_service();
    released = service;
    const std::array<ParameterAssignment, 2> unknown{{
        {"camera_index", integer(0)},
        {"raw_output", ParameterValue::from(true)},
    }};
    ASSERT_FALSE(add_capture(graph, "camera", service, unknown));
  }
  // Key assertion: with the caller's copy gone, nothing in the Graph keeps the service.
  EXPECT_TRUE(released.expired());
}

TEST(SIPLCaptureOpCatalogTest, CompiledPlansKeepTheServiceAfterTheGraph) {
  std::weak_ptr<camera::SIPLCaptureService> released;
  std::optional<holoscan::ExecutionPlan> plan;
  {
    holoscan::Graph graph{"sipl_capture_catalog_plan_lifetime"};
    auto service = test_service();
    released = service;
    const std::array<ParameterAssignment, 2> values{{
        {"camera_index", integer(0)},
        {"memory_kind", ParameterValue::from(std::string_view{"host"})},
    }};
    auto added = add_capture(graph, "camera", std::move(service), values);
    ASSERT_TRUE(added) << added.error().message;
    const auto sink = graph.op<NullFrameSinkOp>("sink");
    graph.add_flow(CaptureHandle::of(added->op)->frame, sink->input,
                   holoscan::ConnectionOptions{.queue_depth = 1U});
    graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));
    plan.emplace(holoscan::compile(graph));
    ASSERT_TRUE(plan->ok()) << plan->json();
  }
  // Key assertion: the plan keeps the service after the Graph is gone, and releases it with it.
  EXPECT_FALSE(released.expired());
  plan.reset();
  EXPECT_TRUE(released.expired());
}

TEST(SIPLCaptureOpCatalogTest, RejectsANullService) {
  auto handle = holoscan::authoring::ConstructorHandle::from_shared(
      camera::sipl_capture_service_handle_type(), std::shared_ptr<camera::SIPLCaptureService>{});
  ASSERT_FALSE(handle);
  EXPECT_NE(handle.error().message.find("AUTHORING_CONSTRUCTOR_HANDLE_NULL"), std::string::npos)
      << handle.error().message;
}

TEST(SIPLCaptureOpCatalogTest, AcceptsNarrowIntegersAndRejectsDuplicates) {
  holoscan::Graph graph{"sipl_capture_catalog_parsing"};

  // A narrower integer than the field's is accepted.
  const std::array<ParameterAssignment, 1> narrow{{
      {"camera_index", ParameterValue::from(std::uint8_t{1})},
  }};
  auto added = add_capture(graph, "narrow", test_service(), narrow);
  ASSERT_TRUE(added) << added.error().message;
  EXPECT_EQ(CaptureHandle::of(added->op)->memory_kind(), holoscan::MemoryKind::kCudaDevice);

  const std::array<ParameterAssignment, 2> duplicate{{
      {"camera_index", integer(0)},
      {"camera_index", integer(1)},
  }};
  auto rejected = add_capture(graph, "duplicate", test_service(), duplicate);
  ASSERT_FALSE(rejected);
  EXPECT_NE(rejected.error().message.find("AUTHORING_PARAMETER_DUPLICATE"), std::string::npos)
      << rejected.error().message;
}

TEST(SIPLCaptureOpCatalogTest, RegistryBuiltCaptureCompiles) {
  for (const std::string_view memory_kind : {"host", "device"}) {
    holoscan::Graph graph{"sipl_capture_catalog_compile"};
    const std::array<ParameterAssignment, 2> assignments{{
        {"camera_index", integer(0)},
        {"memory_kind", ParameterValue::from(memory_kind)},
    }};
    auto added = add_capture(graph, "camera", test_service(), assignments);
    ASSERT_TRUE(added) << added.error().message;
    const auto camera = CaptureHandle::of(added->op);
    const auto sink = graph.op<NullFrameSinkOp>("sink");
    graph.add_flow(camera->frame, sink->input, holoscan::ConnectionOptions{.queue_depth = 1U});
    graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));

    holoscan::CompileOptions compile_options;
    if (memory_kind == "device") {
      compile_options.deployment.bind_tensor_output_device(holoscan::TensorOutputDevicePlacement{
          .operator_path = "camera", .output_port = "frame", .device = holoscan::DeviceId{0}});
    }
    const holoscan::ExecutionPlan plan = holoscan::compile(graph, std::move(compile_options));
    EXPECT_TRUE(plan.ok()) << memory_kind << ": " << plan.json();
  }
}
