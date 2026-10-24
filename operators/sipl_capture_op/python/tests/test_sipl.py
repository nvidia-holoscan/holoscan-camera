# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SIPL capture in Python graphs, without a camera.

A SIPLCaptureService initializes NvSIPL only when asked about its cameras, and constructing or
compiling a graph runs no operator.
"""

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

import holoscan as hs
import holoscan_camera
from holoscan_camera.operators import SIPLCaptureOp
from holoscan_camera.schema import SIPLFrameMetadata

SERVICE_TYPE = "holoscan.camera.SIPLCaptureService"
SAMPLE = (
    Path(__file__).resolve().parents[4]
    / "applications/sipl_capture/python/sipl_capture.py"
)


def load_sample():
    spec = importlib.util.spec_from_file_location("sipl_capture", SAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_graph(service=None, **parameters):
    graph = hs.Graph("sipl-python")
    if service is None:
        service = holoscan_camera.SIPLCaptureService()
    camera = graph.op(SIPLCaptureOp, "camera", service=service, **parameters)
    graph.set_default_clock(graph.add_clock(hs.RealtimeClock, "clock"))
    return graph, camera


def device_options():
    options = hs.CompileOptions()
    options.deployment.bind_tensor_output_device(
        operator_path="camera", output_port="frame", device=hs.execution.DeviceId(0)
    )
    return options


class FrameSinkOp(hs.Operator):
    input = hs.Input("input", hs.schema.Image)

    def setup(self, spec):
        spec.input(self.input, queue_depth=1)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context):
        self.input.receive_data()


class MetadataSinkOp(hs.Operator):
    input = hs.Input("input", SIPLFrameMetadata)

    def setup(self, spec):
        spec.input(self.input, queue_depth=4)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context):
        self.input.selected_sample()


class MetadataSourceOp(hs.Operator):
    """Publishes a SIPLFrameMetadata record every 100 ms, up to 10, unless the run stops."""

    output = hs.Output("output", SIPLFrameMetadata)
    emitted = 0

    def setup(self, spec):
        spec.output(self.output)

    def contract(self):
        return (
            hs.Contract().trigger(hs.OnClock(period=hs.time.ms(100))).complete_after(10)
        )

    def compute(self, context):
        type(self).emitted += 1
        self.output.emit(
            SIPLFrameMetadata(hsb_valid=True, hsb_frame_number=type(self).emitted),
            options=hs.EmitOptions(capture_time=context.activation_time),
        )


@pytest.mark.parametrize("camera_first", [False, True])
def test_import_order_registers_the_metadata_payload(camera_first):
    imports = ["import holoscan", "import holoscan_camera"]
    if camera_first:
        imports.reverse()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(imports)
            + """
from holoscan_camera.operators import SIPLCaptureOp
from holoscan_camera.schema import SIPLFrameMetadata
assert SIPLCaptureOp.frame.payload_type == "holoscan.schema.Image"
assert SIPLCaptureOp.sensor_data.payload_type == SIPLFrameMetadata._registry_name
assert holoscan.payload.resolve(SIPLFrameMetadata._registry_name).name == SIPLFrameMetadata._registry_name
""",
        ],
        check=True,
        timeout=15,
    )


def test_catalog_is_idempotent_and_constructor_is_introspectable():
    import holoscan_camera.operators as operators

    importlib.reload(operators)
    assert operators.SIPLCaptureOp is SIPLCaptureOp
    assert SIPLCaptureOp.name == "holoscan.camera.SIPLCaptureOp"
    assert SIPLCaptureOp.parameter_introspection == "constructor_replay"
    assert set(SIPLCaptureOp.ports) == {"frame", "sensor_data"}
    assert set(SIPLCaptureOp.parameters) == {"camera_index", "memory_kind"}
    assert SIPLCaptureOp.required_parameters == {"camera_index"}
    service = SIPLCaptureOp.constructor_handles["service"]
    assert service.type_name == SERVICE_TYPE
    assert service.required


def test_camera_module_alias_preserves_the_service_type():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import holoscan.camera
import holoscan_camera
assert holoscan.camera.SIPLCaptureService is holoscan_camera.SIPLCaptureService
assert holoscan.camera.operators.SIPLCaptureOp is holoscan_camera.operators.SIPLCaptureOp
""",
        ],
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("memory_kind", ["host", "pinned", "device"])
def test_capture_graph_compiles_without_opening_a_camera(memory_kind):
    graph, camera = make_graph(camera_index=0, memory_kind=memory_kind)
    frames = graph.op(FrameSinkOp, "frames")
    sensor_data = graph.op(MetadataSinkOp, "sensor_data")
    graph.add_flow(camera.frame, frames.input, queue_depth=1)
    graph.add_flow(camera.sensor_data, sensor_data.input, queue_depth=4)
    if memory_kind == "device":
        plan = hs.compile(graph, device_options())
    else:
        plan = hs.compile(graph)
    assert plan.ok, plan.json()


def test_default_device_output_requires_an_explicit_gpu_binding():
    graph, _ = make_graph(camera_index=0)
    plan = hs.compile(graph)
    assert not plan.ok
    assert {"DEVICE_UNRESOLVED", "IMPLICIT_DEVICE_ZERO_REJECTED"} & {
        error.token for error in plan.errors
    }
    placed = hs.compile(graph, device_options())
    assert placed.ok, placed.json()


@pytest.mark.parametrize(
    "parameters",
    [
        {"camera_index": -1},
        {"camera_index": 2**32},
        {"camera_index": "0"},
        {"camera_index": 0, "memory_kind": "managed"},
        {"camera_index": 0, "memory_kind": "cuda_device"},
        {"camera_index": 0, "unknown": 1},
    ],
)
def test_invalid_constructor_arguments_are_rejected(parameters):
    with pytest.raises((hs.errors.HoloscanError, TypeError, ValueError)):
        make_graph(**parameters)


def test_camera_index_is_required():
    with pytest.raises(TypeError, match="missing required parameters: camera_index"):
        make_graph(memory_kind="host")


def test_failed_add_leaves_the_graph_unchanged():
    graph = hs.Graph("sipl-python-failed-add")
    service = holoscan_camera.SIPLCaptureService()
    with pytest.raises((hs.errors.HoloscanError, ValueError)):
        graph.op(
            SIPLCaptureOp, "camera", service=service, camera_index=0, memory_kind="x"
        )
    # Key assertion: the name is free again.
    graph.op(
        SIPLCaptureOp, "camera", service=service, camera_index=0, memory_kind="host"
    )


def test_the_cameras_of_a_configuration_take_one_service():
    graph = hs.Graph("sipl-python-shared-service")
    service = holoscan_camera.SIPLCaptureService()
    cameras = [
        graph.op(SIPLCaptureOp, f"camera{index}", service=service, camera_index=index)
        for index in range(2)
    ]
    # The C++ catalog test checks that both hold the same service, which the graph keeps alive.
    for camera in cameras:
        assert f"service=<{SERVICE_TYPE}: process-local>" in repr(camera)


def test_capture_needs_a_sipl_capture_service():
    graph = hs.Graph("sipl-python-service-type")
    with pytest.raises(hs.errors.IncompatibleError, match="PROTOCOL_MISSING"):
        graph.op(SIPLCaptureOp, "plain", service=object(), camera_index=0)
    with pytest.raises(
        hs.errors.InvalidArgumentError,
        match="AUTHORING_CONSTRUCTOR_HANDLE_REQUIRED field=service",
    ):
        graph.op(SIPLCaptureOp, "missing", camera_index=0)

    class OtherProvider:
        def __holoscan_constructor_handle__(self, type_name):
            return NotImplemented

    with pytest.raises(
        hs.errors.IncompatibleError, match="TYPE_MISMATCH field=service"
    ):
        graph.op(SIPLCaptureOp, "other", service=OtherProvider(), camera_index=0)


def test_the_graph_holds_the_service_not_its_python_wrapper():
    graph = hs.Graph("sipl-python-wrapper")
    service = holoscan_camera.SIPLCaptureService()
    before = sys.getrefcount(service)
    graph.op(SIPLCaptureOp, "camera", service=service, camera_index=0)
    # Key assertion: the operator holds the C++ service, so the wrapper gains no reference.
    assert sys.getrefcount(service) == before


def test_camera_info_is_constructible():
    info = holoscan_camera.CameraInfo()
    info.output_name = "camera0"
    info.width = 1920
    info.bayer_format = holoscan_camera.BayerFormat.GRBG
    assert (info.output_name, info.width, info.bayer_format) == (
        "camera0",
        1920,
        holoscan_camera.BayerFormat.GRBG,
    )


def test_importing_the_package_again_reuses_its_types():
    # Key setup: drop the package from sys.modules and import it again, in a fresh interpreter
    # (a failed re-registration of the native types would abort it).
    code = (
        "import sys\n"
        "import holoscan_camera\n"
        "for name in [n for n in sys.modules if n.startswith('holoscan_camera')]:\n"
        "    del sys.modules[name]\n"
        "import holoscan_camera\n"
        "assert 'SIPLCaptureOp' in holoscan_camera.operators.__all__\n"
        "assert holoscan_camera.SIPLCaptureService().__class__.__name__ == 'SIPLCaptureService'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_sample_metadata_printer_logs_and_stops_the_run_at_its_frame_limit(capfd):
    MetadataSourceOp.emitted = 0
    graph = hs.Graph("sipl-python-sink", default_clock=hs.RealtimeClock)
    source = graph.op(MetadataSourceOp, "source")
    printer = graph.op(
        load_sample().MetadataPrinter,
        "printer",
        camera="test_camera",
        print_metadata=True,
        frame_limit=3,
    )
    graph.add_flow(source.output, printer.metadata, queue_depth=4)
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    with hs.run_async(plan) as session:
        stopped = session.wait(10.0)
    assert stopped, "the printer did not stop the run"
    assert session.termination != hs.RunTermination.FAILED, session.summary()
    output = capfd.readouterr()
    log = output.out + output.err
    # Key assertion: the printer logged frames 1 to 3 and stopped the run before the 4th reached
    # it (the source would have published 10).
    for frame in (1, 2, 3):
        assert f"[test_camera] frame={frame}," in log
    assert "[test_camera] frame=4," not in log
    assert MetadataSourceOp.emitted < 10


def test_metadata_round_trip_uses_the_generated_native_adapter():
    expected = SIPLFrameMetadata(
        frame_capture_start_tsc=2**40 + 7,
        frame_capture_end_tsc=2**40 + 1007,
        hsb_valid=True,
        hsb_frame_number=11,
        frame_timestamp_valid=True,
        frame_timestamp=2**50 + 13,
        width=1920,
        height=1080,
    )

    class Source(hs.Operator):
        out = hs.Output("out", SIPLFrameMetadata)

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
        inp = hs.Input("in", SIPLFrameMetadata)
        received = None

        def setup(self, spec):
            spec.input(self.inp)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.inp))

        def compute(self, context):
            type(self).received = self.inp.receive_data()
            context.request_completion()

    graph = hs.Graph("sipl-metadata-round-trip", default_clock=hs.RealtimeClock)
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


@pytest.mark.parametrize("memory_kind", ["device", "pinned", "host"])
def test_sample_validates_without_opening_a_camera(memory_kind):
    result = subprocess.run(
        [sys.executable, str(SAMPLE), "--memory-kind", memory_kind, "--validate"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "SIPL Python graph validation complete" in result.stdout
