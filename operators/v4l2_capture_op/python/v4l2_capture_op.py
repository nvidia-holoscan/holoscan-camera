# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""V4L2 capture operator for use with ``holoscan.Graph.op``."""

from holoscan.registry import resolve as _resolve

from .. import _camera as _camera

V4l2CaptureOp = _resolve("holoscan.camera.V4l2CaptureOp", kind="operator")

__all__ = ["V4l2CaptureOp"]
