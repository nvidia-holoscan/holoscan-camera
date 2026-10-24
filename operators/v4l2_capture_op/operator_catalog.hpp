// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <holoscan/core/errors.hpp>
#include <holoscan/core/expected.hpp>

namespace holoscan::camera {

/// Register V4L2's immutable constructor in the SDK's language-neutral authoring registry.
/// Repeated calls are safe. Registration never opens a camera or starts capture.
/// See python/README.md#operator-registration for Camera's registration flow and SDK references.
/// SDK guide: docs/python_registered_operators.mdx ("Registered Operators").
/// SDK C++ API: holoscan/authoring/registry.hpp (RegisteredOperatorType) and
/// holoscan/authoring/register_operator.hpp (ManualOperatorRegistrationThunks).
[[nodiscard]] holoscan::expected<void, holoscan::Error> register_v4l2_operator_catalog();

}  // namespace holoscan::camera
