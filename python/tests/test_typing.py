# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check the generated facade as a consumer, including rejected constructor arguments."""

import json
import os
import subprocess
import sys

import pytest

from holoscan_camera import operators


@pytest.mark.skipif(
    not hasattr(operators, "V4l2CaptureOp"), reason="V4L2 provider disabled"
)
@pytest.mark.parametrize(
    "expression,valid",
    [
        ('V4l2CaptureOp(graph, "camera")', True),
        (
            'V4l2CaptureOp(graph, "camera", device="/dev/video0", width=640, height=480, '
            'fps=30, frame_id="camera", memory_kind="host")',
            True,
        ),
        ('V4l2CaptureOp(graph, "camera", memory_kind="pinned")', True),
        ('V4l2CaptureOp(graph, "camera", memory_kind="device")', True),
        ('V4l2CaptureOp(graph, "camera", memory_kind=1)', True),
        ('V4l2CaptureOp(graph, "camera", memory_kind=2)', True),
        ('V4l2CaptureOp(graph, "camera", memory_kind=3)', True),
        ('V4l2CaptureOp(graph, "camera", width="640")', False),
        ('V4l2CaptureOp(graph, "camera", device=0)', False),
        ('V4l2CaptureOp(graph, "camera", memory_kind="managed")', False),
        ('V4l2CaptureOp(graph, "camera", memory_kind=4)', False),
        ('V4l2CaptureOp(graph, "camera", unknown=1)', False),
        ('V4l2CaptureOp(graph, "camera").missing_port', False),
    ],
)
def test_consumer_types(tmp_path, expression, valid):
    check_consumer_types(tmp_path, expression, valid, "V4l2CaptureOp")


@pytest.mark.skipif(
    "ArgusCaptureOp" not in operators.__all__, reason="Argus provider disabled"
)
@pytest.mark.parametrize(
    "expression,valid",
    [
        ('ArgusCaptureOp(graph, "camera")', True),
        (
            'ArgusCaptureOp(graph, "camera", pixel_format="i420", memory_kind="host")',
            True,
        ),
        ('ArgusCaptureOp(graph, "camera", integration_start_offset_ns=None)', True),
        ('ArgusCaptureOp(graph, "camera", integration_start_offset_ns=-100)', True),
        ('ArgusCaptureOp(graph, "camera", drop_policy=1, pixel_format=0)', True),
        ('ArgusCaptureOp(graph, "camera", drop_policy="drop_newest")', True),
        ('ArgusCaptureOp(graph, "camera", drop_policy="drop-newest")', False),
        ('ArgusCaptureOp(graph, "camera").metadata', True),
        ('ArgusCaptureOp(graph, "camera", width="1920")', False),
        ('ArgusCaptureOp(graph, "camera", pixel_format="rgb")', False),
        ('ArgusCaptureOp(graph, "camera", drop_policy="block")', False),
        ('ArgusCaptureOp(graph, "camera", integration_start_offset_ns="100")', False),
        ('ArgusCaptureOp(graph, "camera", unknown=1)', False),
        ('ArgusCaptureOp(graph, "camera").missing_port', False),
    ],
)
def test_argus_consumer_types(tmp_path, expression, valid):
    check_consumer_types(tmp_path, expression, valid, "ArgusCaptureOp")


@pytest.mark.skipif(
    "SIPLCaptureOp" not in operators.__all__, reason="SIPL provider disabled"
)
@pytest.mark.parametrize(
    "expression,valid",
    [
        ('SIPLCaptureOp(graph, "camera", service=service, camera_index=1)', True),
        (
            'SIPLCaptureOp(graph, "camera", service=service, camera_index=0, '
            'memory_kind="host")',
            True,
        ),
        (
            'SIPLCaptureOp(graph, "camera", service=service, camera_index=0, '
            'memory_kind="pinned")',
            True,
        ),
        (
            'SIPLCaptureOp(graph, "camera", service=service, camera_index=0, memory_kind=3)',
            True,
        ),
        ("camera.sensor_data", True),
        ('SIPLCaptureOp(graph, "camera", camera_index=0)', False),
        ('SIPLCaptureOp(graph, "camera", service=service)', False),
        ('SIPLCaptureOp(graph, "camera", service=object(), camera_index=0)', False),
        ('SIPLCaptureOp(graph, "camera", service=service, camera_index="0")', False),
        (
            'SIPLCaptureOp(graph, "camera", service=service, camera_index=0, '
            'memory_kind="cuda_device")',
            False,
        ),
        (
            'SIPLCaptureOp(graph, "camera", service=service, camera_index=0, unknown=1)',
            False,
        ),
        ("camera.missing_port", False),
    ],
)
def test_sipl_consumer_types(tmp_path, expression, valid):
    check_consumer_types(
        tmp_path,
        expression,
        valid,
        "SIPLCaptureOp",
        prelude=(
            "import holoscan_camera",
            "service = holoscan_camera.SIPLCaptureService()",
        ),
        camera_arguments=", service=service, camera_index=0",
    )


def check_consumer_types(
    tmp_path, expression, valid, operator, prelude=(), camera_arguments=""
):
    lines = [
        "import holoscan",
        f"from holoscan_camera.operators import {operator}",
        "graph = holoscan.Graph()",
        *prelude,
        f'camera = {operator}(graph, "typed"{camera_arguments})',
        "frame: holoscan.Port = camera.frame",
        expression,
    ]
    source = tmp_path / "consumer.py"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = tmp_path / "pyrightconfig.json"
    config.write_text(json.dumps({"typeCheckingMode": "strict"}), encoding="utf-8")
    result = subprocess.run(
        [
            os.environ["HOLOSCAN_CAMERA_PYRIGHT"],
            "--pythonpath",
            sys.executable,
            "--project",
            str(config),
            "--outputjson",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stdout + result.stderr
    report = json.loads(result.stdout)
    errors = [d for d in report["generalDiagnostics"] if d["severity"] == "error"]
    if valid:
        assert result.returncode == 0 and not errors, result.stdout
    else:
        assert result.returncode == 1 and errors, result.stdout
        # An unresolved import or unrelated SDK error must not satisfy a negative test.
        assert all(d["range"]["start"]["line"] == len(lines) - 1 for d in errors), (
            result.stdout
        )
