// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <holoscan/core/errors.hpp>
#include <holoscan/core/expected.hpp>

namespace holoscan::camera {

/// Register Argus's immutable constructor in the SDK's language-neutral authoring registry.
/// Repeated calls are safe. Registration never opens a camera or starts capture.
[[nodiscard]] holoscan::expected<void, holoscan::Error> register_argus_operator_catalog();

}  // namespace holoscan::camera
