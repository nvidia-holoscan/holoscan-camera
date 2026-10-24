# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise sample deadlines, cleanup, placement, and CLI interpreter selection."""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import holoscan as hs
from holoscan.schema import Header, Image
from holoscan.schema.image import ImageEncoding

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sample():
    spec = importlib.util.spec_from_file_location(
        "v4l2_sample",
        ROOT / "applications/holoscan_camera_v4l2/python/v4l2_capture.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sessions(monkeypatch):
    real_run_async = hs.run_async
    created = []

    def record_session(plan):
        session = real_run_async(plan)
        created.append(session)
        return session

    monkeypatch.setattr(hs, "run_async", record_session)
    return created


def probe_plan(*, complete=False, fail=False):
    class Probe(hs.Operator):
        def contract(self):
            return hs.Contract().trigger(hs.OnClock(period=hs.time.ms(1)))

        def compute(self, context):
            if fail:
                raise RuntimeError("sample-test-failure")
            if complete:
                context.request_completion()

    graph = hs.Graph("sample-probe", default_clock=hs.RealtimeClock)
    graph.op(Probe, "probe")
    plan = hs.compile(graph)
    assert plan.ok, plan.summary()
    return plan


def test_capture_deadline_stops_and_joins_session(sample, sessions):
    with pytest.raises(TimeoutError, match="V4L2 capture exceeded --timeout"):
        sample.run_capture(probe_plan(), 0.05)
    assert len(sessions) == 1
    assert not sessions[0].is_running
    assert sessions[0].termination == hs.RunTermination.STOPPED


def test_capture_completes_before_deadline(sample, sessions):
    sample.run_capture(probe_plan(complete=True), 5.0)
    assert sessions[0].termination == hs.RunTermination.REQUESTED_COMPLETED


def test_capture_reports_runtime_failure(sample, sessions):
    with pytest.raises(RuntimeError, match="sample-test-failure"):
        sample.run_capture(probe_plan(fail=True), 5.0)
    assert sessions[0].termination == hs.RunTermination.FAILED


def image_source():
    class Source(hs.Operator):
        frame = hs.Output("frame", Image)

        def setup(self, spec):
            spec.output(self.frame).produces_tensor(
                hs.tensor.OutputSpec(
                    storage="runtime_pool",
                    memory_kind=hs.tensor.MemoryKind.HOST,
                    dtype="uint8",
                    rank=2,
                    transfer=hs.tensor.TensorTransferPolicy(
                        foreign_emit_policy=hs.tensor.InterfaceTensorEmitPolicy.COPY_IF_NEEDED
                    ),
                ),
                hs.tensor.byte_span(8),
                field="data",
            )

        def contract(self):
            return (
                hs.Contract()
                .trigger(hs.OnClock(period=hs.time.ms(1)))
                .complete_after(1)
            )

        def compute(self, context):
            import numpy as np

            self.frame.emit(
                Image(
                    width=2,
                    height=2,
                    encoding=ImageEncoding.YUYV,
                    header=Header(frame_id="preview_camera", device_sequence=17),
                    data=hs.Tensor.as_tensor(
                        np.arange(8, dtype=np.uint8).reshape(2, 4)
                    ),
                ),
                options=hs.EmitOptions(frame_id=17, flags=hs.SampleFlags.DEGRADED),
            )

    return Source


def test_preview_adapter_preserves_pixels_and_metadata(sample):
    import numpy as np

    received = []

    class Inspect(hs.Operator):
        image = hs.Input("image", Image)

        def setup(self, spec):
            spec.input(self.image)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.image))

        def compute(self, context):
            item = self.image.receive()
            image = item.data
            pixels = np.from_dlpack(image.data)
            assert pixels.shape == (2, 2, 2)
            assert pixels.dtype == np.uint8
            np.testing.assert_array_equal(
                pixels.reshape(2, 4), np.arange(8).reshape(2, 4)
            )
            assert (image.width, image.height) == (2, 2)
            assert image.encoding == ImageEncoding.YUYV
            assert image.header.frame_id == "preview_camera"
            assert image.header.device_sequence == 17
            assert item.metadata.frame_id == 17
            assert item.metadata.degraded
            received.append(pixels.copy())

    graph = hs.Graph("preview-layout", default_clock=hs.RealtimeClock)
    source = graph.op(image_source(), "source")
    adapter = graph.op(sample.YuyvPreviewOp, "adapter", width=2, height=2)
    sink = graph.op(Inspect, "sink")
    graph.add_flow(source.frame, adapter.image)
    graph.add_flow(adapter.frame, sink.image)
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    sample.run_capture(plan, 5.0)
    assert len(received) == 1


def test_preview_adapter_rejects_unexpected_dimensions(sample):
    graph = hs.Graph("preview-invalid-layout", default_clock=hs.RealtimeClock)
    source = graph.op(image_source(), "source")
    adapter = graph.op(sample.YuyvPreviewOp, "adapter", width=4, height=2)
    sink = graph.op(sample.FrameCounterOp, "counter", count=0)
    graph.add_flow(source.frame, adapter.image)
    graph.add_flow(adapter.frame, sink.image)
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    with pytest.raises(RuntimeError, match="Preview requires YUYV images"):
        sample.run_capture(plan, 5.0)


def test_frame_counter_requests_completion(sample, sessions, capsys):
    graph = hs.Graph("frame-limit", default_clock=hs.RealtimeClock)
    source = graph.op(image_source(), "source")
    counter = graph.op(sample.FrameCounterOp, "counter", count=1)
    graph.add_flow(source.frame, counter.image)
    plan = hs.compile(graph)
    assert plan.ok, plan.json()
    sample.run_capture(plan, 5.0)
    assert sessions[0].termination == hs.RunTermination.REQUESTED_COMPLETED
    assert "frame 1: 2x2" in capsys.readouterr().out


@pytest.mark.parametrize("memory_kind", ["host", "pinned"])
def test_holoviz_preview_graph_compiles_without_camera_or_display(
    sample, monkeypatch, memory_kind
):
    pytest.importorskip("holoscan_visualization.operators")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "v4l2_capture.py",
            "--validate",
            "--preview",
            "--memory-kind",
            memory_kind,
            "--yuv-model",
            "bt709",
            "--yuv-range",
            "full",
        ],
    )
    sample.main()


@pytest.mark.parametrize("memory_kind", ["host", "pinned", "device"])
def test_sample_placement_options_compile(sample, monkeypatch, memory_kind):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "v4l2_capture.py",
            "--validate",
            "--memory-kind",
            memory_kind,
            "--frame-id",
            "review_camera",
            "--timeout",
            "2",
            "--cuda-device",
            "0",
        ],
    )
    sample.main()


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--timeout", "-1"], "--timeout must be finite and positive"),
        (["--timeout", "0"], "--timeout must be finite and positive"),
        (["--timeout", "nan"], "--timeout must be finite and positive"),
        (["--timeout", "inf"], "--timeout must be finite and positive"),
        (["--cuda-device", "-1"], "--cuda-device must be nonnegative"),
        (
            ["--preview", "--memory-kind", "device"],
            "--preview requires --memory-kind host or pinned",
        ),
    ],
)
def test_sample_rejects_invalid_options(
    sample, monkeypatch, capsys, arguments, message
):
    monkeypatch.setattr(sys, "argv", ["v4l2_capture.py", "--validate", *arguments])
    with pytest.raises(SystemExit) as error:
        sample.main()
    assert error.value.code == 2
    assert message in capsys.readouterr().err


def test_cli_metadata_uses_exact_selected_interpreter(tmp_path):
    # A versioned interpreter can share a directory with an incompatible python3.
    # Exercise the actual metadata command, including quoting of paths with spaces.
    directory = tmp_path / "python installation"
    directory.mkdir()
    selected = directory / "python3.12"
    selected.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    selected.chmod(0o755)
    wrong = directory / "python3"
    wrong.write_text("#!/bin/sh\necho 'wrong interpreter' >&2\nexit 86\n")
    wrong.chmod(0o755)
    metadata = json.loads(
        (ROOT / "applications/holoscan_camera_v4l2/python/metadata.json").read_text()
    )
    command = metadata["application"]["modes"]["validate"]["run"]["command"]
    result = subprocess.run(
        shlex.split(command.replace("<holohub_root>", str(ROOT))),
        env={
            **os.environ,
            "HOLOSCAN_CLI_PYTHON_BIN": str(selected),
            "PATH": str(directory) + os.pathsep + os.environ["PATH"],
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V4L2 Python graph validation complete" in result.stdout
