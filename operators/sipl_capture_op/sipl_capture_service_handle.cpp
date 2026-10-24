// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sipl_capture_op/sipl_capture_service_handle.hpp"

namespace holoscan::camera {

namespace {
constexpr authoring::ConstructorHandleDescriptor kServiceHandleDescriptor{
    .name = "holoscan.camera.SIPLCaptureService",
    .description = "NvSIPL camera configuration (holoscan_camera.SIPLCaptureService).",
};
}  // namespace

const authoring::ConstructorHandleType<SIPLCaptureService>& sipl_capture_service_handle_type() {
  static const authoring::ConstructorHandleType<SIPLCaptureService> type{kServiceHandleDescriptor};
  return type;
}

}  // namespace holoscan::camera
