# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the real V4L2 constructor and graph planner without opening a camera."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import holoscan as hs
from holoscan_camera.operators import V4l2CaptureOp

DEVICE = "/dev/holoscan-python-test-missing"


def make_graph(**parameters):
    graph = hs.Graph("v4l2-python-parity")
    camera = graph.op(V4l2CaptureOp, "camera", device=DEVICE, **parameters)
    graph.set_default_clock(graph.add_clock(hs.RealtimeClock, "clock"))
    return graph, camera


@pytest.mark.parametrize("camera_first", [False, True])
def test_canonical_import_order_registers_image_and_camera(camera_first):
    imports = ["import holoscan", "import holoscan_camera"]
    if camera_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
from holoscan_camera.operators import V4l2CaptureOp
assert V4l2CaptureOp.frame.payload_type == "holoscan.schema.Image"
assert holoscan.payload.resolve("holoscan.schema.Image").name == "holoscan.schema.Image"
import sys
assert "holoscan_camera._argus" not in sys.modules
assert "holoscan_camera._sipl" not in sys.modules
assert not hasattr(holoscan_camera.operators, "SiplCaptureOp")
""",
        ],
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("alias_first", [False, True])
def test_discovered_alias_preserves_native_provider_identity(alias_first):
    entries = tuple(
        importlib.metadata.entry_points(group="holoscan.modules", name="camera")
    )
    # The build tree and installs advertise the real provider, without conflicts.
    assert len(entries) == 1
    assert entries[0].value == "holoscan_camera"
    imports = ["holoscan_camera.operators", "holoscan.camera.operators"]
    if alias_first:
        imports.reverse()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import_order = {imports!r}\n"
            + """
import importlib
import sys
import holoscan as hs

# Discovering metadata must not eagerly initialize the native camera provider.
assert "holoscan_camera" not in sys.modules
first = importlib.import_module(import_order[0])
registered = hs.registry.resolve("holoscan.camera.V4l2CaptureOp", kind="operator")
second = importlib.import_module(import_order[1])
assert first is second
assert first.V4l2CaptureOp is second.V4l2CaptureOp is registered
assert importlib.import_module("holoscan.camera") is importlib.import_module("holoscan_camera")
assert importlib.import_module("holoscan.camera._camera") is importlib.import_module(
    "holoscan_camera._camera"
)
from holoscan import camera
assert camera is sys.modules["holoscan_camera"]
assert camera.operators is first
assert sum(op.name == registered.name for op in hs.registry.operators()) == 1
assert registered.frame.payload_type == "holoscan.schema.Image"

graph = hs.Graph("discovered-camera", default_clock=hs.RealtimeClock)
graph.op(first.V4l2CaptureOp, "camera", device="/dev/holoscan-python-test-missing")
plan = hs.compile(graph)
assert plan.ok, plan.summary()
""",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_constructor_metadata_is_introspectable():
    assert V4l2CaptureOp.name == "holoscan.camera.V4l2CaptureOp"
    assert set(V4l2CaptureOp.ports) == {"frame"}
    assert set(V4l2CaptureOp.parameters) == {
        "device",
        "width",
        "height",
        "fps",
        "frame_id",
        "memory_kind",
    }


@pytest.mark.parametrize("memory_kind", ["host", 1, "pinned", 2])
def test_constructor_and_compile_do_not_open_the_device(memory_kind):
    graph, camera = make_graph(memory_kind=memory_kind)
    assert camera.frame.payload_type.name == "holoscan.schema.Image"
    plan = hs.compile(graph)
    assert plan.ok, [error.token for error in plan.errors]


@pytest.mark.parametrize(
    "parameters,error_type,message",
    [
        (
            {"width": 3},
            hs.errors.FailureError,
            "GRAPH_OPERATOR_CONSTRUCTION_FAILED: YUYV capture width must be even",
        ),
        (
            {"width": 0},
            hs.errors.InvalidArgumentError,
            "PARAM_VALIDATION_FAILED category=out_of_range .*field_name=width",
        ),
        (
            {"height": -1},
            hs.errors.InvalidArgumentError,
            "PARAM_VALIDATION_FAILED category=out_of_range .*field_name=height",
        ),
        (
            {"fps": 0},
            hs.errors.InvalidArgumentError,
            "PARAM_VALIDATION_FAILED category=out_of_range .*field_name=fps",
        ),
        (
            {"fps": 1_000_000_001},
            hs.errors.InvalidArgumentError,
            "PARAM_VALIDATION_FAILED category=out_of_range .*field_name=fps",
        ),
        (
            {"frame_id": ""},
            hs.errors.FailureError,
            "GRAPH_OPERATOR_CONSTRUCTION_FAILED: V4L2 frame_id must name a coordinate frame",
        ),
        (
            {"memory_kind": "managed"},
            hs.errors.InvalidArgumentError,
            "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=memory_kind",
        ),
        (
            {"width": "640"},
            hs.errors.InvalidArgumentError,
            "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=width",
        ),
        (
            {"width": 2**64},
            hs.errors.InvalidArgumentError,
            "AUTHORING_PARAMETER_TYPE_MISMATCH field_name=width",
        ),
        (
            {"unknown_parameter": 1},
            hs.errors.InvalidArgumentError,
            "AUTHORING_PARAMETER_UNKNOWN field_name=unknown_parameter",
        ),
    ],
)
def test_invalid_constructor_arguments_are_rejected(parameters, error_type, message):
    with pytest.raises(error_type, match=message):
        make_graph(**parameters)


def test_empty_device_is_rejected():
    with pytest.raises(
        hs.errors.FailureError,
        match="GRAPH_OPERATOR_CONSTRUCTION_FAILED: V4L2 device path must not be empty",
    ):
        hs.Graph("invalid-device").op(V4l2CaptureOp, "camera", device="")


@pytest.mark.parametrize("memory_kind", ["device", 3])
def test_gpu_placement_remains_an_explicit_compile_requirement(memory_kind):
    graph, _ = make_graph(memory_kind=memory_kind)
    plan = hs.compile(graph)
    assert not plan.ok
    # The planner distinguishes a missing GPU from rejecting implicit GPU zero
    # on a machine where CUDA devices are available.
    assert {"DEVICE_UNRESOLVED", "IMPLICIT_DEVICE_ZERO_REJECTED"} & {
        error.token for error in plan.errors
    }


def test_explicit_gpu_placement_is_retained_in_the_plan():
    graph, _ = make_graph(memory_kind="device", width=320, height=240)
    options = hs.CompileOptions()
    options.deployment.bind_tensor_output_device(
        operator_path="camera", output_port="frame", device=hs.execution.DeviceId(0)
    )
    plan = hs.compile(graph, options)
    assert plan.ok, plan.json()
    (allocation,) = json.loads(plan.json())["tensor_allocations"]
    assert allocation["device"] == 0
    assert allocation["memory_kind"] == hs.tensor.MemoryKind.CUDA_DEVICE.value
    assert allocation["bounds"]["max_byte_span"] == 320 * 240 * 2


def test_embedded_cameras_preserve_independent_constructor_arguments():
    class CameraGraph(hs.Graph):
        def __init__(self, *, width, height, memory_kind):
            super().__init__()
            self.arguments = dict(width=width, height=height, memory_kind=memory_kind)

        def compose(self):
            self.clock = self.import_clock("timeline")
            self.set_default_clock(self.clock)
            self.op(V4l2CaptureOp, "camera", device=DEVICE, **self.arguments)

    graph = hs.Graph("embedded-cameras", default_clock=hs.RealtimeClock)
    small = graph.embed(CameraGraph, "small", width=320, height=240, memory_kind="host")
    large = graph.embed(
        CameraGraph, "large", width=640, height=480, memory_kind="pinned"
    )
    graph.bind_clock(small, small.clock, graph.default_clock())
    graph.bind_clock(large, large.clock, graph.default_clock())
    # Repeated compilation must preserve each embedded native constructor's geometry
    # and memory placement, without opening either device.
    for _ in range(2):
        plan = hs.compile(graph)
        assert plan.ok, plan.summary()
        allocations = json.loads(plan.json())["tensor_allocations"]
        assert sorted(
            (a["memory_kind"], a["bounds"]["max_byte_span"]) for a in allocations
        ) == [
            (hs.tensor.MemoryKind.HOST.value, 320 * 240 * 2),
            (hs.tensor.MemoryKind.PINNED_HOST.value, 640 * 480 * 2),
        ]


@pytest.mark.parametrize(
    "preview_args",
    [
        [],
        ["--preview", "--frames", "0"],
        ["--preview", "--frames", "0", "--timeout", "0"],
    ],
)
def test_sample_compiles_a_python_consumer_without_opening_a_camera(preview_args):
    if "--preview" in preview_args:
        try:
            importlib.import_module("holoscan_visualization.operators")
        except ModuleNotFoundError as error:
            if error.name not in (
                "holoscan_visualization",
                "holoscan_visualization.operators",
            ):
                raise
            pytest.skip("Preview validation requires optional Holoscan Visualization")
    sample = (
        Path(__file__).resolve().parents[2]
        / "applications/holoscan_camera_v4l2/python/v4l2_capture.py"
    )
    result = subprocess.run(
        [sys.executable, str(sample), "--device", DEVICE, "--validate", *preview_args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "V4L2 Python graph validation complete" in result.stdout


def test_python_and_cpp_author_the_same_plan():
    graph, _ = make_graph(width=320, height=240, fps=15, frame_id="test_camera")
    plan = hs.compile(graph)
    assert plan.ok, [error.token for error in plan.errors]
    native = subprocess.run(
        [os.environ["HOLOSCAN_CAMERA_PLAN_HELPER"]],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert json.loads(plan.json()) == json.loads(native.stdout)
