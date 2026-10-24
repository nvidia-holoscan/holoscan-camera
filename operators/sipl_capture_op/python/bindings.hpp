// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <nanobind/nanobind.h>

namespace holoscan::camera {

/// Add SIPLCaptureService, CameraInfo, PixelFormat, and BayerFormat to the provider module.
/// nanobind registers a C++ type once per process, so a module imported again attaches the types
/// already registered instead.
void bind_sipl_types(nanobind::module_& module);

}  // namespace holoscan::camera
