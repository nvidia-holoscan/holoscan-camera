# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# fmt: off

# ruff: noqa: E501 - registry metadata intentionally remains on generated lines

"""Camera capture Operators registered by holoscan_camera."""

from holoscan.operators import OperatorHandle as _OperatorHandle
from holoscan.registry import OperatorType as _OperatorType

__all__: list[str] = ['ArgusCaptureOp']


# Registry-backed operator proxy types.
from typing import Final, Literal, Never, TypedDict, Unpack

import holoscan
from holoscan.registry import OperatorParameterInfo as _OperatorParameterInfo
from holoscan.registry import OperatorPortInfo as _OperatorPortInfo


class _ArgusCaptureOpParams(TypedDict, total=False):
    camera_index: int
    sensor_mode: int
    width: int
    height: int
    fps: float
    pixel_format: Literal['nv12', 0, 'i420', 1]
    buffer_count: int
    drop_policy: Literal['drop_oldest', 0, 'drop_newest', 1]
    timeout_ms: int
    cuda_device: int
    frame_id: str
    memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3]
    integration_start_offset_ns: int | None


class _ArgusCaptureOpHandle(_OperatorHandle):
    frame: holoscan.Port
    metadata: holoscan.Port
    def __getattr__(self, name: Never) -> Never: ...  # type: ignore[misc, override]


class _ArgusCaptureOpType(_OperatorType[_ArgusCaptureOpHandle]):
    "Capture NV12/I420 images and frame metadata on Jetson AGX Orin. Device output requires an explicit GPU binding.\n\nRegistry name: holoscan.camera.ArgusCaptureOp\n\nPorts:\n  frame: Output[holoscan.schema.Image]\n  metadata: Output[holoscan.camera.ArgusFrameMetadata]\n\nParameters:\n  camera_index: int — Camera index in libargus enumeration, not a /dev/videoN index.\n  sensor_mode: int — Sensor mode index in libargus enumeration.\n  width: int, range (2, 16384) — Even output width in pixels.\n  height: int, range (2, 16384) — Even output height in pixels.\n  fps: float, range (0.1, 1000.0) — Requested frames per second.\n  pixel_format: Literal['nv12', 0, 'i420', 1], choices nv12, i420 — Packed NV12 or I420 output layout.\n  buffer_count: int, range (3, 64) — Number of native Argus capture buffers.\n  drop_policy: Literal['drop_oldest', 0, 'drop_newest', 1], choices drop_oldest, drop_newest — Queue overflow policy.\n  timeout_ms: int, range (100, 60000) — No-frame deadline in milliseconds; must also cover one frame period.\n  cuda_device: int, range (0, 0) — Jetson integrated GPU ordinal; only zero is supported.\n  frame_id: str — Image coordinate frame name, containing 1 to 256 bytes.\n  memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3], choices host, pinned, device — Output tensor placement; device requires an explicit GPU binding.\n  integration_start_offset_ns: int | None — Optional calibrated integration-start offset from VI SOF, in nanoseconds."
    Handle: Final[type[_ArgusCaptureOpHandle]]
    Params: Final[type[_ArgusCaptureOpParams]]
    buffer_count: _OperatorParameterInfo
    camera_index: _OperatorParameterInfo
    cuda_device: _OperatorParameterInfo
    drop_policy: _OperatorParameterInfo
    fps: _OperatorParameterInfo
    frame: _OperatorPortInfo
    frame_id: _OperatorParameterInfo
    height: _OperatorParameterInfo
    integration_start_offset_ns: _OperatorParameterInfo
    memory_kind: _OperatorParameterInfo
    metadata: _OperatorPortInfo
    pixel_format: _OperatorParameterInfo
    sensor_mode: _OperatorParameterInfo
    timeout_ms: _OperatorParameterInfo
    width: _OperatorParameterInfo
    def __call__(self, graph: holoscan.Graph, instance_name: str, **params: Unpack[_ArgusCaptureOpParams]) -> _ArgusCaptureOpHandle: ...  # type: ignore[override]

ArgusCaptureOp: Final[_ArgusCaptureOpType]
