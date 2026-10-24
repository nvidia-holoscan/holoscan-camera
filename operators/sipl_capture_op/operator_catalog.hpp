// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <holoscan/core/errors.hpp>
#include <holoscan/core/expected.hpp>

namespace holoscan::camera {

/// Register SIPL's operator in the SDK's language-neutral authoring registry:
/// `holoscan.camera.SIPLCaptureOp`.
///
/// `SIPLCaptureOp` takes its SIPLCaptureService as the required `service` constructor handle
/// (sipl_capture_service_handle.hpp), shared by the operators of the configuration's cameras, and
/// the immutable constructor values `camera_index` (required) and `memory_kind` (`host`,
/// `pinned`, or the default `device`, which needs an explicit GPU binding).
///
/// Repeated calls are safe and return the first call's result. Registration never opens a camera.
[[nodiscard]] holoscan::expected<void, holoscan::Error> register_sipl_operator_catalog();

}  // namespace holoscan::camera
