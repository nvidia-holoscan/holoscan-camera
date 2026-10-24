// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <nanobind/nanobind.h>

#include <holoscan/sensor_io/sensor_schema_package.hpp>

#ifdef HOLOSCAN_CAMERA_PYTHON_V4L2
#include "v4l2_capture_op/operator_catalog.hpp"
#endif

NB_MODULE(_camera, module) {
  // Core owns Image's Python value/codec and the process-wide registry. Import it first.
  nanobind::module_::import_("holoscan");
  (void)holoscan::sensor_io::register_sensor_schema_payloads();
#ifdef HOLOSCAN_CAMERA_PYTHON_V4L2
  auto registered = holoscan::camera::register_v4l2_operator_catalog();
  if (!registered) throw holoscan::RuntimeError{registered.error()};
#endif
  module.doc() = "Register the native Holoscan Camera operator catalog.";
}
