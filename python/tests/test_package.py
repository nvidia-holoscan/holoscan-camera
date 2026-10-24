# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check selected exports in a fresh interpreter for each enabled capture backend."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("camera_first", [False, True])
def test_provider_alias_uses_packaged_metadata(camera_first):
    imports = ["import holoscan.camera", "import holoscan_camera"]
    if camera_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
from importlib.metadata import distribution

entry_points = distribution("holoscan-camera-cu13").entry_points
assert any(ep.group == "holoscan.modules" and ep.name == "camera"
           and ep.value == "holoscan_camera" for ep in entry_points)
assert holoscan.camera is holoscan_camera
assert holoscan.camera.operators is holoscan_camera.operators
""",
        ],
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("camera_first", [False, True])
def test_selected_operator_exports(camera_first):
    imports = ["import holoscan", "import holoscan_camera"]
    if camera_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
import importlib
import sys
from pathlib import Path

operators = holoscan_camera.operators
package = Path(operators.__file__).parent
names = {"v4l2": "V4l2CaptureOp", "argus": "ArgusCaptureOp", "sipl": "SIPLCaptureOp"}
expected = [alias for backend, alias in names.items()
            if (package / (backend + "_capture_op.py")).is_file()]
assert operators.__all__ == expected
assert importlib.reload(operators).__all__ == expected
assert 'holoscan_camera._argus' not in sys.modules
assert 'holoscan_camera._sipl' not in sys.modules
assert not hasattr(operators, "SiplCaptureOp")

if EXPECT_V4L2:
    from holoscan_camera.operators import V4l2CaptureOp
    assert V4l2CaptureOp is holoscan.registry.resolve("holoscan.camera.V4l2CaptureOp")
    assert V4l2CaptureOp is importlib.import_module(
        "holoscan_camera.operators.v4l2_capture_op").V4l2CaptureOp
registered = [op.name for op in holoscan.registry.operators()
              if op.name.startswith("holoscan.camera.")]
assert registered == (["holoscan.camera.V4l2CaptureOp"] if EXPECT_V4L2 else [])
# Merely importing the schema namespace must not import either metadata adapter.
if (package.parent / "schema").is_dir():
    import holoscan_camera.schema
    assert 'holoscan_camera.schema.argus_frame_metadata' not in sys.modules
    assert 'holoscan_camera.schema.sipl_frame_metadata' not in sys.modules
assert 'holoscan_camera._argus' not in sys.modules
assert 'holoscan_camera._sipl' not in sys.modules

stub = package / "__init__.pyi"
if stub.exists():
    for backend, alias in names.items():
        assert (package / (backend + "_capture_op.pyi")).is_file() == (alias in expected)
else:
    assert not list(package.parent.rglob("*.pyi"))
    assert not (package.parent / "py.typed").exists()
""".replace("EXPECT_V4L2", repr(os.environ["HOLOSCAN_CAMERA_EXPECT_V4L2"] == "1"))
            .replace(
                "EXPECT_ARGUS",
                repr(os.environ.get("HOLOSCAN_CAMERA_EXPECT_ARGUS") == "1"),
            )
            .replace(
                "EXPECT_SIPL",
                repr(os.environ.get("HOLOSCAN_CAMERA_EXPECT_SIPL") == "1"),
            ),
        ],
        check=True,
        timeout=15,
    )
