# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check that Camera ships a complete, provider-owned typing surface."""

import ast
import importlib
import os

import pytest
from pathlib import Path

from holoscan_camera import operators


@pytest.mark.parametrize("alias", operators.__all__)
def test_operator_typing_covers_the_native_constructor_and_ports(alias):
    backend = {
        "ArgusCaptureOp": "argus",
        "SIPLCaptureOp": "sipl",
        "V4l2CaptureOp": "v4l2",
    }[alias]
    # CTest selects only built backends whose runtime tests are enabled. Preserve
    # the original all-R39 opt-in for direct invocations, unless explicitly selected.
    default_backends = (
        "v4l2,argus,sipl"
        if os.environ.get("HOLOSCAN_CAMERA_TEST_R39") == "1"
        else "v4l2"
    )
    selected = os.environ.get("HOLOSCAN_CAMERA_TEST_BACKENDS", default_backends)
    if backend not in selected.split(","):
        pytest.skip(
            f"{backend} typing requires explicit compatible-runtime qualification"
        )
    package = Path(operators.__file__).parent.parent
    assert (package / "py.typed").is_file()
    assert (package / "_camera.pyi").is_file()
    facade = importlib.import_module(f"holoscan_camera.operators.{backend}_capture_op")
    text = Path(facade.__file__).with_suffix(".pyi").read_text(encoding="utf-8")
    tree = ast.parse(text)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    proxy = getattr(operators, alias)
    parameters = {
        node.target.id: ast.unparse(node.annotation)
        for node in classes[f"_{alias}Params"].body
        if isinstance(node, ast.AnnAssign)
    }
    # A row's constructor handles are typed with its parameters.
    assert set(parameters) == set(proxy.parameters) | set(proxy.constructor_handles)
    ports = {
        node.target.id
        for node in classes[f"_{alias}Handle"].body
        if isinstance(node, ast.AnnAssign)
    }
    assert ports == set(proxy.ports)
    assert f"{alias}: Final[_{alias}Type]" in text
    if alias == "ArgusCaptureOp":
        assert parameters["integration_start_offset_ns"] == "int | None"
        assert parameters["pixel_format"] == "Literal['nv12', 0, 'i420', 1]"
        assert (
            parameters["memory_kind"] == "Literal['host', 1, 'pinned', 2, 'device', 3]"
        )
    if alias == "SIPLCaptureOp":
        assert parameters["service"] == "Required[holoscan_camera.SIPLCaptureService]"
        assert parameters["camera_index"] == "Required[int]"
        assert (
            parameters["memory_kind"] == "Literal['host', 1, 'pinned', 2, 'device', 3]"
        )
