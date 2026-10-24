// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Standalone C++ reference for test_python_and_cpp_author_the_same_plan in test_v4l2.py.
// CTest supplies this executable's path through HOLOSCAN_CAMERA_PLAN_HELPER. The Python
// test runs it as a subprocess and compares its stdout JSON with an independently
// compiled Python graph's plan. The C++ graph itself is not imported into Python.
// Compilation does not start capture or open the device. See python/README.md#graph-tests.

// clang-format off: Keep standard headers before SDK headers for cpplint.
#include <iostream>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/time/realtime_clock.hpp>

#include "v4l2_capture_op/v4l2_capture_op.hpp"
#include "v4l2_capture_op/operator_catalog.hpp"
// clang-format on

int main() {
  // Exercise native registration twice; reloading the Python facade does not.
  for (int attempt = 0; attempt < 2; ++attempt) {
    if (!holoscan::camera::register_v4l2_operator_catalog()) return 1;
  }
  holoscan::Graph graph{"v4l2-python-parity"};
  graph.op<holoscan::camera::V4l2CaptureOp>("camera", "/dev/holoscan-python-test-missing",
                                         320, 240, 15, "test_camera",
                                         holoscan::MemoryKind::kHost);
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));
  auto plan = holoscan::compile(graph);
  std::cout << plan.json();
  return plan.ok() ? 0 : 1;
}
