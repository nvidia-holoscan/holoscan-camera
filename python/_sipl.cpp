// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <nanobind/nanobind.h>

#include "sipl_capture_op/operator_catalog.hpp"
#include "sipl_capture_op/python/bindings.hpp"

NB_MODULE(_sipl, module) {
  // Keep this backend's BSP dependencies outside the portable _camera initializer.
  // Load shared payload support and the metadata adapter before registering its catalog.
  nanobind::module_::import_("holoscan_camera._camera");
  nanobind::module_::import_("holoscan_camera.schema.sipl_frame_metadata");
  auto registered = holoscan::camera::register_sipl_operator_catalog();
  if (!registered) throw holoscan::RuntimeError{registered.error()};
  // Service/value types are direct bindings; the operator itself is a Core registry proxy.
  holoscan::camera::bind_sipl_types(module);
  module.doc() = "Register the native SIPL Camera backend.";
}
