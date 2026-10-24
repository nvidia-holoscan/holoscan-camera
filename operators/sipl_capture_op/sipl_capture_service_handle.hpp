// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// The Holoscan SDK constructor-handle type of SIPLCaptureService, through which a registered
// operator receives a live service (SIPLCaptureOp's `service` input).

#pragma once

#include <holoscan/authoring/constructor_handle.hpp>

#include "sipl_capture_op/sipl_capture_service.hpp"

namespace holoscan::camera {

/// @brief The constructor-handle type of SIPLCaptureService, stable name
/// `holoscan.camera.SIPLCaptureService`.
///
/// The descriptor is defined once, in the sipl_capture_op library that owns SIPLCaptureService.
/// Python's `holoscan_camera.SIPLCaptureService` exports its handle through it, and a C++ host can
/// build one with `authoring::ConstructorHandle::from_shared(sipl_capture_service_handle_type(),
/// service)`.
[[nodiscard]] const authoring::ConstructorHandleType<SIPLCaptureService>&
sipl_capture_service_handle_type();

}  // namespace holoscan::camera
