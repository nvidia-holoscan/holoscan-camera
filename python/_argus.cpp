// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <nanobind/nanobind.h>

#include "argus_capture_op/operator_catalog.hpp"

NB_MODULE(_argus, module) {
  // Keep this backend's BSP dependencies outside the portable _camera initializer.
  // Load shared payload support and the metadata adapter before registering its catalog.
  nanobind::module_::import_("holoscan_camera._camera");
  nanobind::module_::import_("holoscan_camera.schema.argus_frame_metadata");
  auto registered = holoscan::camera::register_argus_operator_catalog();
  if (!registered) throw holoscan::RuntimeError{registered.error()};
  module.doc() = "Register the native ARGUS Camera backend.";
}
