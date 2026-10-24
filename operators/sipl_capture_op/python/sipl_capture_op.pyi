# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# fmt: off

# ruff: noqa: E501 - registry metadata intentionally remains on generated lines

"""Camera capture Operators registered by holoscan_camera."""

from holoscan.operators import OperatorHandle as _OperatorHandle
from holoscan.registry import OperatorType as _OperatorType

__all__: list[str] = ['SIPLCaptureOp']


# Registry-backed operator proxy types.
from typing import Final, Literal, Never, Required, TypedDict, Unpack

import holoscan
import holoscan_camera
from holoscan.registry import OperatorParameterInfo as _OperatorParameterInfo
from holoscan.registry import OperatorPortInfo as _OperatorPortInfo


class _SIPLCaptureOpParams(TypedDict, total=False):
    service: Required[holoscan_camera.SIPLCaptureService]
    camera_index: Required[int]
    memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3]


class _SIPLCaptureOpHandle(_OperatorHandle):
    frame: holoscan.Port
    sensor_data: holoscan.Port
    def __getattr__(self, name: Never) -> Never: ...  # type: ignore[misc, override]


class _SIPLCaptureOpType(_OperatorType[_SIPLCaptureOpHandle]):
    "Registered Operator holoscan.camera.SIPLCaptureOp.\n\nRegistry name: holoscan.camera.SIPLCaptureOp\n\nPorts:\n  frame: Output[holoscan.schema.Image]\n  sensor_data: Output[holoscan.camera.SIPLFrameMetadata]\n\nParameters:\n  camera_index: int — Zero-based index of the camera within the service's configuration.\n  memory_kind: Literal['host', 1, 'pinned', 2, 'device', 3], choices host, pinned, device — Output tensor placement; device requires an explicit GPU binding.\n\nConstructor handles:\n  service: holoscan.camera.SIPLCaptureService, required — The SIPL camera configuration, shared by the operators of its cameras."
    Handle: Final[type[_SIPLCaptureOpHandle]]
    Params: Final[type[_SIPLCaptureOpParams]]
    camera_index: _OperatorParameterInfo
    frame: _OperatorPortInfo
    memory_kind: _OperatorParameterInfo
    sensor_data: _OperatorPortInfo
    def __call__(self, graph: holoscan.Graph, instance_name: str, **params: Unpack[_SIPLCaptureOpParams]) -> _SIPLCaptureOpHandle: ...  # type: ignore[override]

SIPLCaptureOp: Final[_SIPLCaptureOpType]
