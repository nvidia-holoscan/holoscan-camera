# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Registry-backed SIPL operator for Holoscan SDK 5 graphs."""

from importlib import import_module as _import_module

from holoscan.registry import resolve as _resolve

# Import for catalog-registration side effects before resolving the Core proxy.
# The package namespace defers this facade import until its operator is requested.
try:
    _import_module("holoscan_camera._sipl")
except ImportError as error:
    raise ImportError(
        "SIPL requires an ARM64 Camera build and a compatible R39 BSP runtime; "
        "V4L2 remains available through holoscan_camera.operators.V4l2CaptureOp"
    ) from error

SIPLCaptureOp = _resolve("holoscan.camera.SIPLCaptureOp", kind="operator")

__all__ = ["SIPLCaptureOp"]
