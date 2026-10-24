# SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runs sipl_player.py's tiled graph headless for two fake cameras that capture together, in place
of SIPLCaptureOp, and reads back which frame of each camera every render shows. Needs a GPU with
Vulkan, for HoloViz; no camera. (Raw10UnpackOp is tested with the holoscan_camera package.)

Each test runs its session in a process of its own: in a process's second session with HoloViz,
the SDK's teardown can crash (in OutputPool::close, recording a CUDA event)."""

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import cupy as cp
import holoscan as hs
import pytest
from holoscan.schema.image import ImageEncoding, ImagePlaneLayout
from holoscan_camera.operators.converters import writable_view
from holoscan_camera.schema import SIPLFrameMetadata

_SPEC = importlib.util.spec_from_file_location(
    "sipl_player", Path(__file__).resolve().parents[1] / "sipl_player.py"
)
sipl_player = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sipl_player)

_UINT8 = hs.tensor.DLDataType(1, 8, 1)
_WIDTH, _HEIGHT = 256, 128
_LUMA_BYTES = _WIDTH * _HEIGHT
_NV12_BYTES = _LUMA_BYTES * 3 // 2
# The fake cameras' rate: 30 frames per second, half the player's render rate.
_PERIOD = hs.time.ms(33)
# Fewer frames than distinct gray levels, so that a level names one frame.
_FRAMES = 45


def gray_level(frame):
    """The gray level of a fake camera's frame `frame`: 20, 24, ... 216."""
    return 20 + 4 * frame


def frame_shown(level):
    """The frame whose gray level a render shows, or None for no frame (black)."""
    if level < 10:
        return None
    return round((level - 20) / 4)


class Ticker(hs.Operator):
    """The fake cameras' frame clock: it ticks once per frame, with the frame's number and capture
    time, so that the cameras capture together, as a hardware-synchronized pair does."""

    tick = hs.Output("tick", hs.payload.uint32)

    def setup(self, spec):
        spec.output(self.tick)

    def contract(self):
        return hs.Contract().trigger(hs.OnClock(period=_PERIOD))

    def start(self):
        self.count = 0

    def compute(self, context):
        self.tick.emit(
            self.count, options=hs.EmitOptions(capture_time=context.activation_time)
        )
        self.count += 1


def fake_camera(*, stall_after=None, capture_offset_us=0, passes_tick=False):
    """An operator with SIPLCaptureOp's outputs, which publishes, on each tick, an NV12 frame of a
    uniform gray level, gray_level(n) for the n-th, captured `capture_offset_us` after the tick,
    and an empty metadata record. After `stall_after` frames, it publishes nothing more. With
    `passes_tick`, it then passes the tick on to `next_tick`."""

    class FakeCamera(hs.Operator):
        tick = hs.Input("tick", hs.payload.uint32)
        frame = hs.Output("frame", hs.schema.Image)
        sensor_data = hs.Output("sensor_data", SIPLFrameMetadata)
        if passes_tick:
            next_tick = hs.Output("next_tick", hs.payload.uint32)

        def setup(self, spec):
            spec.input(self.tick, queue_depth=1)
            if passes_tick:
                spec.output(self.next_tick)
            spec.output(self.frame, max_emits_per_compute=1).produces_tensor(
                hs.tensor.OutputSpec(
                    storage="runtime_pool",
                    memory_kind=hs.tensor.MemoryKind.CUDA_DEVICE,
                    dtype=_UINT8,
                    rank=1,
                ),
                hs.tensor.byte_span(_NV12_BYTES),
                field="data",
            )
            spec.output(self.sensor_data, max_emits_per_compute=1)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.tick))

        def compute(self, context):
            index = self.tick.receive().data
            if index < _FRAMES and (stall_after is None or index < stall_after):
                self._publish_frame(context, index)
            if passes_tick:
                self.next_tick.emit(
                    index, options=hs.EmitOptions(capture_time=context.activation_time)
                )

        def _publish_frame(self, context, index):
            tick = context.activation_time
            capture_time = hs.time.TimePoint(
                tick.timestamp_ns + capture_offset_us * 1000, tick.clock_id
            )
            options = hs.EmitOptions(capture_time=capture_time, frame_id=index)
            descriptor = hs.schema.Image(
                width=_WIDTH,
                height=_HEIGHT,
                encoding=ImageEncoding.NV12,
                plane_layouts=[
                    ImagePlaneLayout(
                        offset_bytes=0, row_stride_bytes=_WIDTH, size_bytes=_LUMA_BYTES
                    ),
                    ImagePlaneLayout(
                        offset_bytes=_LUMA_BYTES,
                        row_stride_bytes=_WIDTH,
                        size_bytes=_LUMA_BYTES // 2,
                    ),
                ],
            )
            request = hs.tensor.LoanRequest(shape=(_NV12_BYTES,), dtype=_UINT8)
            with (
                context.stream(),
                self.frame.allocate_tensors(
                    descriptor, {"data": request}, options=options
                ) as loan,
            ):
                frame = writable_view(loan.tensors["data"], cp.uint8)
                frame[:_LUMA_BYTES] = gray_level(index)
                frame[_LUMA_BYTES:] = 128  # no chroma
            self.sensor_data.emit(SIPLFrameMetadata(), options=options)

    return FakeCamera


class RenderSink(hs.Operator):
    """Stands in for the player's DiscardImageOp: keeps, for each render, the frame each tile
    shows (left: camera0, right: camera1)."""

    input = hs.Input("input", hs.schema.Image)
    renders = []

    def setup(self, spec):
        spec.input(self.input, queue_depth=1)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context):
        sample = self.input.receive()
        with context.stream():
            image = cp.from_dlpack(sample.data.data)
            # The middle of each tile.
            rows = slice(_HEIGHT // 2 - 8, _HEIGHT // 2 + 8)
            tiles = [
                image[rows, center - 8 : center + 8, :3]
                for center in (_WIDTH // 2, _WIDTH + _WIDTH // 2)
            ]
            levels = [float(cp.asnumpy(tile).mean()) for tile in tiles]
        type(self).renders.append(tuple(frame_shown(level) for level in levels))


def run_player(monkeypatch, cameras):
    """Runs the player's graph for the fake `cameras` until the first one's last frame; returns
    each render's [camera0 frame, camera1 frame]. The last camera gets the Ticker's ticks, and
    each camera but the first passes them on to the one before it: of the frames of one tick, the
    first camera's, which drive the rendering, are delivered last (as when the ISP processes the
    first camera's frame last)."""
    added = []

    def add_camera(graph, name, service, index, **kwargs):
        camera = graph.op(cameras[index], name)
        added.append(camera)
        if index == len(cameras) - 1:
            mailbox = {"queue_policy": hs.QueuePolicy.DROP_OLDEST, "queue_depth": 1}
            graph.add_flow(graph.op(Ticker, "ticker").tick, camera.tick, **mailbox)
            for later, earlier in zip(added[:0:-1], added[-2::-1]):
                graph.add_flow(later.next_tick, earlier.tick, **mailbox)
        return camera

    monkeypatch.setattr(sipl_player, "add_camera", add_camera)
    monkeypatch.setattr(sipl_player, "DiscardImageOp", RenderSink)
    RenderSink.renders = []

    infos = sipl_player.placeholder_cameras()
    for info in infos:
        info.width, info.height = _WIDTH, _HEIGHT
    args = argparse.Namespace(
        raw=False,
        headless=True,
        fullscreen=False,
        metadata=False,
        frame_limit=_FRAMES,
        cuda_device=0,
    )
    plan = sipl_player.compile_player(hs.Graph("sipl_player_test"), args, None, infos)
    assert plan.ok, [str(diagnostic) for diagnostic in plan.diagnostics]
    with hs.run_async(plan) as session:
        # The first camera's sensor data sink ends the run at its last frame.
        assert session.wait(timeout=30.0), "the run did not end at --frame-limit"
    assert session.termination != hs.RunTermination.FAILED, session.summary()
    renders = [list(render) for render in RenderSink.renders if None not in render]
    assert len(renders) >= _FRAMES // 2, RenderSink.renders
    return renders


def player_renders(stall_after):
    """The renders of the player's graph for two cameras that capture together, the second 100 us
    after the first, as the sensors of a synchronized pair may, and deliver the second camera's
    frames first; the second camera stops after `stall_after` frames, if given."""
    cameras = [
        fake_camera(),
        fake_camera(stall_after=stall_after, capture_offset_us=100, passes_tick=True),
    ]
    with pytest.MonkeyPatch.context() as monkeypatch:
        return run_player(monkeypatch, cameras)


def run_isolated(scenario, *args):
    """Runs this module's function `scenario` in a Python process of its own, and returns its
    result."""
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        f"import {Path(__file__).stem} as tests\n"
        f"print('RESULT ' + json.dumps(tests.{scenario}(*{args!r})), flush=True)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
    assert result.returncode == 0 and lines, result.stdout + result.stderr
    return json.loads(lines[-1].removeprefix("RESULT "))


def test_second_tile_shows_the_frame_before_the_first_cameras():
    # Key setup: two cameras that capture together (see player_renders()).
    renders = run_isolated("player_renders", None)

    # Key assertion: the window renders every frame of the first camera, with the second camera's
    # frame before it (or the one before that, after a render the window missed); a second tile
    # that falls further behind, or skips ahead, is wrong.
    assert max(left for left, _ in renders) >= _FRAMES - 5, renders
    assert all(1 <= left - right <= 2 for left, right in renders), renders


def test_a_stalled_camera_does_not_stop_the_window():
    # Key setup: the second camera stops after 10 frames.
    renders = run_isolated("player_renders", 10)

    # Key assertion: the window goes on rendering the first camera's frames, with the second
    # camera's last frame.
    assert max(left for left, _ in renders) >= _FRAMES - 5, renders
    assert all(right == 9 for left, right in renders if left >= 20), renders
