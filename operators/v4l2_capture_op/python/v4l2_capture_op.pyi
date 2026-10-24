# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# fmt: off

# ruff: noqa: E501 - registry metadata intentionally remains on generated lines

"""Camera capture Operators registered by holoscan_camera."""

from holoscan.operators import OperatorHandle as _OperatorHandle
from holoscan.registry import OperatorType as _OperatorType

__all__: list[str] = ['V4l2CaptureOp']


# Registry-backed operator proxy types.
from typing import Final, Literal, Never, TypedDict, Unpack

import holoscan
from holoscan.registry import OperatorParameterInfo as _OperatorParameterInfo
from holoscan.registry import OperatorPortInfo as _OperatorPortInfo


class _V4l2CaptureOpParams(TypedDict, total=False):
    device: str
    width: int
    height: int
    fps: int
    frame_id: str
    memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3]


class _V4l2CaptureOpHandle(_OperatorHandle):
    frame: holoscan.Port
    def __getattr__(self, name: Never) -> Never: ...  # type: ignore[misc, override]


class _V4l2CaptureOpType(_OperatorType[_V4l2CaptureOpHandle]):
    "Registered Operator holoscan.camera.V4l2CaptureOp.\n\nRegistry name: holoscan.camera.V4l2CaptureOp\n\nPorts:\n  frame: Output[holoscan.schema.Image]\n\nParameters:\n  device: str — V4L2 device node path.\n  width: int, range (1, 2147483647) — Even YUYV capture width in pixels.\n  height: int, range (1, 2147483647) — Capture height in pixels.\n  fps: int, range (1, 1000000000) — Requested frames per second.\n  frame_id: str — Image coordinate frame name.\n  memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3], choices host, pinned, device — Output tensor placement; device requires an explicit GPU binding."
    Handle: Final[type[_V4l2CaptureOpHandle]]
    Params: Final[type[_V4l2CaptureOpParams]]
    device: _OperatorParameterInfo
    fps: _OperatorParameterInfo
    frame: _OperatorPortInfo
    frame_id: _OperatorParameterInfo
    height: _OperatorParameterInfo
    memory_kind: _OperatorParameterInfo
    width: _OperatorParameterInfo
    def __call__(self, graph: holoscan.Graph, instance_name: str, **params: Unpack[_V4l2CaptureOpParams]) -> _V4l2CaptureOpHandle: ...  # type: ignore[override]

V4l2CaptureOp: Final[_V4l2CaptureOpType]
