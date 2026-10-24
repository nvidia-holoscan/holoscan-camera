# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise native Argus graph authoring and metadata codecs without a camera."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import holoscan as hs
from holoscan_camera.operators import ArgusCaptureOp
from holoscan_camera.schema import ArgusFrameMetadata, ArgusTimestampClock

METADATA_NAME = "holoscan.camera.ArgusFrameMetadata"


def make_graph(**parameters):
    graph = hs.Graph("argus-python-parity")
    camera = graph.op(ArgusCaptureOp, "camera", **parameters)
    graph.set_default_clock(graph.add_clock(hs.RealtimeClock, "clock"))
    return graph, camera


@pytest.mark.parametrize("camera_first", [False, True])
def test_import_order_registers_both_payloads(camera_first):
    imports = ["import holoscan", "import holoscan_camera"]
    if camera_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
from holoscan_camera.operators import ArgusCaptureOp
from holoscan_camera.schema import ArgusFrameMetadata
assert ArgusCaptureOp.frame.payload_type == "holoscan.schema.Image"
assert ArgusCaptureOp.metadata.payload_type == ArgusFrameMetadata._registry_name
assert holoscan.payload.resolve(ArgusFrameMetadata._registry_name).name == ArgusFrameMetadata._registry_name
""",
        ],
        check=True,
        timeout=15,
    )


def test_catalog_is_idempotent_and_constructor_is_introspectable():
    import holoscan_camera.operators as operators

    importlib.reload(operators)
    assert operators.ArgusCaptureOp is ArgusCaptureOp
    assert ArgusCaptureOp.name == "holoscan.camera.ArgusCaptureOp"
    assert "Jetson AGX Orin" in ArgusCaptureOp.__doc__
    assert "explicit GPU binding" in ArgusCaptureOp.__doc__
    assert ArgusCaptureOp.parameter_introspection == "constructor_replay"
    assert set(ArgusCaptureOp.ports) == {"frame", "metadata"}
    assert set(ArgusCaptureOp.parameters) == {
        "camera_index",
        "sensor_mode",
        "width",
        "height",
        "fps",
        "pixel_format",
        "buffer_count",
        "drop_policy",
        "timeout_ms",
        "cuda_device",
        "frame_id",
        "memory_kind",
        "integration_start_offset_ns",
    }


def test_core_import_does_not_load_camera_catalog():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import holoscan
from holoscan.registry import operators
assert 'holoscan_camera' not in sys.modules
assert not any(op.name.startswith('holoscan.camera.') for op in operators())
assert not hasattr(holoscan, 'ArgusCaptureOp')
""",
        ],
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("alias_first", [False, True])
def test_camera_module_alias_preserves_package_and_extension_identity(alias_first):
    imports = ["import holoscan_camera", "import holoscan.camera"]
    if alias_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
import importlib
assert holoscan.camera is holoscan_camera
for child in ('operators', 'schema', '_camera', 'schema.argus_frame_metadata',
              'schema._argus_frame_metadata_holoscan'):
    canonical = importlib.import_module('holoscan_camera.' + child)
    alias = importlib.import_module('holoscan.camera.' + child)
    assert alias is canonical, child
assert not hasattr(holoscan, 'ArgusCaptureOp')
""",
        ],
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("pixel_format,drop_policy,memory_kind", [(0, 0, 1), (1, 1, 2)])
def test_direct_constructor_and_named_enum_graph_authoring_produce_the_same_plan(
    pixel_format, drop_policy, memory_kind
):
    direct = hs.Graph("argus-constructor-parity", default_clock=hs.RealtimeClock)
    ArgusCaptureOp(
        direct,
        "camera",
        camera_index=999999,
        pixel_format=pixel_format,
        drop_policy=drop_policy,
        memory_kind=memory_kind,
    )
    named = hs.Graph("argus-constructor-parity", default_clock=hs.RealtimeClock)
    named.op(
        ArgusCaptureOp,
        "camera",
        camera_index=999999,
        pixel_format=("nv12", "i420")[pixel_format],
        drop_policy=("drop_oldest", "drop_newest")[drop_policy],
        memory_kind={1: "host", 2: "pinned"}[memory_kind],
    )
    direct_plan, named_plan = hs.compile(direct), hs.compile(named)
    assert direct_plan.ok, direct_plan.json()
    assert named_plan.ok, named_plan.json()
    assert json.loads(direct_plan.json()) == json.loads(named_plan.json())


@pytest.mark.parametrize("memory_kind", ["host", "pinned"])
@pytest.mark.parametrize("pixel_format", ["nv12", "i420"])
def test_constructor_and_compile_do_not_open_a_camera(memory_kind, pixel_format):
    graph, camera = make_graph(
        camera_index=999999, memory_kind=memory_kind, pixel_format=pixel_format
    )
    assert camera.frame.payload_type.name == "holoscan.schema.Image"
    assert camera.metadata.payload_type.name == METADATA_NAME
    plan = hs.compile(graph)
    assert plan.ok, plan.json()


@pytest.mark.parametrize("offset", [None, 0, -100, 100])
def test_optional_calibrated_offset_is_materialized(offset):
    graph, _ = make_graph(memory_kind="host", integration_start_offset_ns=offset)
    plan = hs.compile(graph)
    assert plan.ok, plan.json()


@pytest.mark.parametrize(
    "parameters,field",
    [
        ({"camera_index": -1}, "camera_index"),
        ({"sensor_mode": 2**32}, "sensor_mode"),
        ({"pixel_format": "rgb"}, "pixel_format"),
        ({"drop_policy": "block"}, "drop_policy"),
        ({"drop_policy": "drop-oldest"}, "drop_policy"),
        ({"memory_kind": "managed"}, "memory_kind"),
        ({"integration_start_offset_ns": 2**63}, "integration_start_offset_ns"),
        ({"width": "1920"}, "width"),
    ],
)
def test_invalid_constructor_types_are_rejected(parameters, field):
    with pytest.raises(
        hs.errors.InvalidArgumentError,
        match=rf"AUTHORING_PARAMETER_TYPE_MISMATCH field_name={field}",
    ):
        make_graph(**parameters)


@pytest.mark.parametrize(
    "parameters,field",
    [
        ({"width": 0}, "width"),
        ({"height": 16386}, "height"),
        ({"fps": 0}, "fps"),
        ({"fps": float("nan")}, "fps"),
        ({"fps": float("inf")}, "fps"),
        ({"fps": 1001}, "fps"),
        ({"buffer_count": 2}, "buffer_count"),
        ({"buffer_count": 65}, "buffer_count"),
        ({"timeout_ms": 99}, "timeout_ms"),
        ({"timeout_ms": 60001}, "timeout_ms"),
        ({"cuda_device": 1}, "cuda_device"),
    ],
)
def test_constructor_schema_ranges_are_enforced(parameters, field):
    with pytest.raises(
        hs.errors.InvalidArgumentError,
        match=rf"PARAM_VALIDATION_FAILED category=out_of_range .*field_name={field}",
    ):
        make_graph(**parameters)


@pytest.mark.parametrize(
    "parameters,message",
    [
        ({"width": 3}, "Argus width and height must be even"),
        ({"height": 3}, "Argus width and height must be even"),
        ({"frame_id": ""}, "Argus frame_id must contain 1 to 256 bytes"),
        ({"frame_id": "x" * 257}, "Argus frame_id must contain 1 to 256 bytes"),
    ],
)
def test_native_constructor_validation_reaches_python(parameters, message):
    with pytest.raises(
        hs.errors.FailureError, match=f"GRAPH_OPERATOR_CONSTRUCTION_FAILED: {message}"
    ):
        make_graph(**parameters)


def test_unknown_constructor_argument_is_rejected():
    with pytest.raises(
        hs.errors.InvalidArgumentError,
        match="AUTHORING_PARAMETER_UNKNOWN field_name=unknown",
    ):
        make_graph(unknown=1)


def test_native_cross_field_validation_reaches_python():
    with pytest.raises(
        hs.errors.FailureError,
        match="GRAPH_OPERATOR_CONSTRUCTION_FAILED: Argus timeout_ms must cover a frame period",
    ):
        make_graph(fps=0.1, timeout_ms=2000)


def test_default_device_output_requires_an_explicit_gpu_binding():
    graph, _ = make_graph()
    plan = hs.compile(graph)
    assert not plan.ok
    assert {"DEVICE_UNRESOLVED", "IMPLICIT_DEVICE_ZERO_REJECTED"} & {
        error.token for error in plan.errors
    }
    options = hs.CompileOptions()
    options.deployment.bind_tensor_output_device(
        operator_path="camera", output_port="frame", device=hs.execution.DeviceId(0)
    )
    placed = hs.compile(graph, options)
    assert placed.ok, placed.json()


@pytest.mark.parametrize("pixel_format", ["nv12", "i420"])
def test_sample_compiles_both_python_consumers(pixel_format):
    sample = (
        Path(__file__).resolve().parents[4]
        / "applications/holoscan_camera_argus/python/argus_capture.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(sample),
            "--camera",
            "999999",
            "--format",
            pixel_format,
            "--validate",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "Argus Python graph validation complete" in result.stdout


def test_python_and_cpp_author_the_same_plan():
    graph, _ = make_graph(
        camera_index=17,
        sensor_mode=3,
        width=640,
        height=480,
        fps=29.97,
        pixel_format="i420",
        buffer_count=8,
        drop_policy="drop_newest",
        timeout_ms=2345,
        cuda_device=0,
        frame_id="test_camera",
        memory_kind="host",
        integration_start_offset_ns=-123,
    )
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    native = subprocess.run(
        [os.environ["HOLOSCAN_CAMERA_PLAN_HELPER"]],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert json.loads(plan.json()) == json.loads(native.stdout)


def test_embedded_capture_replays_independent_constructor_values():
    # SDK embedding and compilation clone the retained native constructor factory.
    # Different image sizes expose accidental reuse of defaults or another instance.
    class Capture(hs.Graph):
        def __init__(self, **parameters):
            super().__init__()
            self.capture_parameters = parameters

        def compose(self):
            self.clock = self.import_clock("timeline")
            self.set_default_clock(self.clock)
            self.op(ArgusCaptureOp, "camera", **self.capture_parameters)
            self.capture_parameters["width"] = 1920

    graph = hs.Graph("argus-constructor-replay")
    clock = graph.add_clock(hs.RealtimeClock, "clock")
    for name, width, height in (("left", 640, 480), ("right", 1280, 720)):
        capture = graph.embed(
            Capture,
            name,
            camera_index=999999,
            width=width,
            height=height,
            memory_kind="host",
            drop_policy="drop_newest",
        )
        graph.bind_clock(capture, capture.clock, clock)

    first, replayed = hs.compile(graph), hs.compile(graph)
    assert first.ok, first.json()
    assert replayed.ok, replayed.json()
    result = json.loads(first.json())
    assert result == json.loads(replayed.json())
    assert sorted(
        allocation["bounds"]["max_byte_span"]
        for allocation in result["tensor_allocations"]
    ) == [640 * 480 * 3 // 2, 1280 * 720 * 3 // 2]


def test_metadata_round_trip_uses_the_generated_native_adapter():
    expected = ArgusFrameMetadata(
        camera_index=2,
        sensor_mode=3,
        source_index=4,
        sequence=2**40 + 7,
        sensor_timestamp_ns=2**50 + 11,
        sensor_sof_timestamp_ns=2**50 + 13,
        timestamp_clock=ArgusTimestampClock.TEGRA_TSC_NS,
        capture_timestamp_ns=-37,
        capture_time_valid=False,
        clock_uncertainty_ns=29,
        exposure_time_ns=15000000,
        frame_duration_ns=33333333,
        analog_gain=1.5,
        isp_digital_gain=2.0,
        ae_locked=True,
        ae_state="AE_STATE_CONVERGED",
        awb_state="AWB_STATE_SEARCHING",
        width=1920,
        height=1080,
        sequence_gap=2,
        sequence_regressed=True,
        queue_drops=3,
        publication_drops=5,
        capture_timeouts=7,
    )

    class Source(hs.Operator):
        out = hs.Output("out", ArgusFrameMetadata)

        def setup(self, spec):
            spec.output(self.out)

        def contract(self):
            return (
                hs.Contract()
                .trigger(hs.OnClock(period=hs.time.ms(1)))
                .complete_after(1)
            )

        def compute(self, context):
            self.out.emit(expected)

    class Sink(hs.Operator):
        inp = hs.Input("in", ArgusFrameMetadata)
        received = None

        def setup(self, spec):
            spec.input(self.inp)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.inp))

        def compute(self, context):
            type(self).received = self.inp.receive_data()
            context.request_completion()

    graph = hs.Graph("argus-metadata-round-trip", default_clock=hs.RealtimeClock)
    source = graph.op(Source, "source")
    sink = graph.op(Sink, "sink")
    graph.add_flow(source.out, sink["in"])
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    with hs.run_async(plan) as session:
        assert session.wait(timeout=5.0)
        assert session.termination != hs.RunTermination.FAILED, session.summary()
    assert Sink.received == expected
    assert Sink.received is not expected
