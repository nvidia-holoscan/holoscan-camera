// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// clang-format off: Keep standard headers before SDK headers for cpplint.
#include <iostream>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/time/realtime_clock.hpp>

#include "argus_capture_op/argus_capture_op.hpp"
// clang-format on

// The constructor schema must be visible to consumers of the public header,
// not only to the translation unit that registers the Python catalog.
static_assert(holoscan::param_schema_availability<holoscan::camera::ArgusCaptureConfig>() ==
              holoscan::ParamSchemaAvailability::kDeclared);

int main() {
  namespace camera = holoscan::camera;
  holoscan::Graph graph{"argus-python-parity"};
  camera::ArgusCaptureConfig config;
  config.camera_index = 17;
  config.sensor_mode = 3;
  config.width = 640;
  config.height = 480;
  config.fps = 29.97;
  config.pixel_format = camera::ArgusPixelFormat::kI420;
  config.buffer_count = 8;
  config.drop_policy = camera::ArgusDropPolicy::kDropNewest;
  config.timeout_ms = 2345;
  config.frame_id = "test_camera";
  config.memory_kind = holoscan::MemoryKind::kHost;
  config.integration_start_offset_ns = -123;
  graph.op<camera::ArgusCaptureOp>("camera", config);
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));
  auto plan = holoscan::compile(graph);
  if (!plan.ok()) {
    std::cerr << plan.json();
    return 1;
  }
  std::cout << plan.json();
  return 0;
}
