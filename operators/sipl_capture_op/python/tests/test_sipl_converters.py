# SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runs holoscan_camera.operators.converters on synthetic frames. Needs a GPU, no camera."""

import dataclasses
import time

import cupy as cp
import holoscan as hs
import numpy as np
import pytest
from holoscan.schema.header import Header
from holoscan.schema.image import ImageEncoding, ImagePlaneLayout

from holoscan_camera.operators import converters

_UINT8 = hs.tensor.DLDataType(1, 8, 1)


@pytest.fixture(autouse=True, scope="module")
def compiled_kernels():
    """Compiles the converters' kernels once, before any run: with a cold cache, the first
    compilation takes seconds, during which a converter falls behind its source."""
    converters.compile_kernels()


def frame_source(
    frames,
    *,
    unstamped=(),
    latency_ms=0,
    period_ms=2,
    memory_kind=hs.tensor.MemoryKind.CUDA_DEVICE,
):
    """An operator that publishes `frames` ((descriptor, bytes) pairs), one every `period_ms`, as
    SIPLCaptureOp does: device-resident bytes, frame ids from 1, and capture times `latency_ms`
    before their publication, but for the frames whose (zero-based) index is in `unstamped`. It
    counts the frames published in `published`. With another `memory_kind`, it publishes the
    frames there, without their bytes."""

    class FrameSource(hs.Operator):
        output = hs.Output("output", hs.schema.Image)
        published = 0

        def setup(self, spec):
            spec.output(self.output).produces_tensor(
                hs.tensor.OutputSpec(
                    storage="runtime_pool",
                    memory_kind=memory_kind,
                    dtype=_UINT8,
                    rank=1,
                ),
                hs.tensor.byte_span(max(data.nbytes for _, data in frames)),
                field="data",
            )

        def contract(self):
            return (
                hs.Contract()
                .trigger(hs.OnClock(period=hs.time.ms(period_ms)))
                .complete_after(len(frames))
            )

        def start(self):
            self.index = 0

        def compute(self, context):
            descriptor, data = frames[self.index]
            self.index += 1
            request = hs.tensor.LoanRequest(shape=data.shape, dtype=_UINT8)
            if self.index - 1 in unstamped:
                options = hs.EmitOptions(frame_id=self.index)
            else:
                now = context.activation_time
                capture_time = hs.time.TimePoint(
                    now.timestamp_ns - latency_ms * 1_000_000, now.clock_id
                )
                options = hs.EmitOptions(capture_time=capture_time, frame_id=self.index)
            with (
                context.stream(),
                self.output.allocate_tensors(
                    descriptor, {"data": request}, options=options
                ) as loan,
            ):
                if memory_kind == hs.tensor.MemoryKind.CUDA_DEVICE:
                    converters.writable_view(loan.tensors["data"], cp.uint8)[...] = (
                        cp.asarray(data)
                    )
            type(self).published += 1
            type(self).capture_times.append(
                options.capture_time.timestamp_ns if options.capture_time else None
            )

    FrameSource.published = 0
    FrameSource.capture_times = []
    return FrameSource


def image_sink(*, retain=False):
    """An operator that keeps what it receives; with `retain`, it also keeps every received
    tensor alive until the run stops, so that the producer's pool runs out."""

    class ImageSink(hs.Operator):
        input = hs.Input("input", hs.schema.Image)
        received = []
        retained = []
        capture_times = []

        def setup(self, spec):
            spec.input(self.input, queue_depth=4)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.input))

        def compute(self, context):
            sample = self.input.receive()
            with context.stream():
                data = cp.asnumpy(cp.from_dlpack(sample.data.data))
            if retain:
                type(self).retained.append(sample.data.data)
            metadata = sample.metadata
            type(self).capture_times.append(
                metadata.capture_timestamp_ns if metadata.source_clock_id != 0 else None
            )
            type(self).received.append(
                (
                    dataclasses.replace(sample.data, data=None),
                    data,
                    sample.metadata.source_clock_id,
                    sample.metadata.frame_id,
                )
            )

        def stop(self):
            type(self).retained.clear()

    ImageSink.received = []
    ImageSink.retained = []
    ImageSink.capture_times = []
    return ImageSink


def run(
    source,
    converter,
    converter_params,
    sink,
    *,
    until=None,
    device_outputs=("source", "converter"),
):
    """Runs source -> converter -> sink to its end or, given `until`, until it returns true (for
    at most 30 s), and stops it then: a graph whose consumer holds its producer's buffers does not
    end on its own. The `device_outputs` operators' outputs are bound to CUDA device 0."""
    graph = hs.Graph("converters_test", default_clock=hs.RealtimeClock)
    source_op = graph.op(source, "source")
    converter_op = graph.op(converter, "converter", **converter_params)
    sink_op = graph.op(sink, "sink")
    graph.add_flow(source_op.output, converter_op.input)
    graph.add_flow(converter_op.output, sink_op.input, queue_depth=4)
    options = hs.CompileOptions()
    for operator_path in device_outputs:
        options.deployment.bind_tensor_output_device(
            operator_path=operator_path,
            output_port="output",
            device=hs.execution.DeviceId(0),
        )
    plan = hs.compile(graph, options)
    assert plan.ok, [str(diagnostic) for diagnostic in plan.diagnostics]
    with hs.run_async(plan) as session:
        if until is None:
            session.wait()
        else:
            deadline = time.monotonic() + 30.0
            while not until() and time.monotonic() < deadline:
                if session.wait(timeout=0.01):
                    break
    return session


# --------------------------------------------------------------------------------------------
# Raw10UnpackOp
# --------------------------------------------------------------------------------------------


def raw10_frame(width=10, height=4, pitch=32, seed=1):
    """A RAW10 frame as SIPLCaptureOp publishes it, with its expected unpacked samples.

    10 pixels per row take 4 words (12 samples); the rows are padded to 32 bytes, and the two
    unused top bits of each word are set, which the unpacking must ignore. A `pitch` too narrow
    for the width cuts the rows short."""
    rng = np.random.default_rng(seed)
    samples = rng.integers(
        0, 1024, size=(height, (width + 2) // 3 * 3), dtype=np.uint32
    )
    rows = np.zeros((height, pitch // 4), dtype=np.uint32)
    words = samples[:, 0::3] | samples[:, 1::3] << 10 | samples[:, 2::3] << 20 | 3 << 30
    columns = min(words.shape[1], rows.shape[1])
    rows[:, :columns] = words[:, :columns]
    descriptor = hs.schema.Image(
        header=Header(frame_id="sipl_camera_0"),
        width=width,
        height=height,
        encoding=ImageEncoding.CUSTOM,
        roi_offset_y=2,
        exposure_time_ns=1000,
    )
    expected = (samples[:, :width] << 6).astype(np.uint16)[..., None]
    return descriptor, rows.view(np.uint8).reshape(-1), expected


def test_raw10_unpack_matches_reference():
    descriptor, data, expected = raw10_frame()
    sink = image_sink()
    session = run(
        frame_source([(descriptor, data)]),
        converters.Raw10UnpackOp,
        {"max_output_bytes": expected.nbytes, "bayer_encoding": "BAYER_GRBG"},
        sink,
    )
    assert session.termination != hs.RunTermination.FAILED, session.summary()

    # Key assertion: every sample lands in the top 10 bits of its pixel, and the frame keeps its
    # descriptor, relabeled with the Bayer phase, and its provenance.
    assert len(sink.received) == 1, session.summary()
    image, unpacked, source_clock_id, frame_id = sink.received[0]
    np.testing.assert_array_equal(unpacked, expected)
    assert (image.width, image.height) == (10, 4)
    assert image.encoding == ImageEncoding.BAYER_GRBG
    assert image.significant_bits == 10
    assert (image.roi_offset_y, image.exposure_time_ns) == (2, 1000)
    assert image.header.frame_id == "sipl_camera_0"
    assert source_clock_id != 0 and frame_id == 1


@pytest.mark.parametrize(
    "memory_kind", [hs.tensor.MemoryKind.HOST, hs.tensor.MemoryKind.PINNED_HOST]
)
@pytest.mark.parametrize("converter", ["Raw10UnpackOp", "Nv12ToRgbOp"])
def test_converters_reject_frames_outside_cuda_device_memory(converter, memory_kind):
    # Key setup: a frame in host memory, as SIPLCaptureOp publishes with memory_kind "host" or
    # "pinned".
    descriptor, data, expected = (
        raw10_frame() if converter == "Raw10UnpackOp" else nv12_frame()
    )
    session = run(
        frame_source([(descriptor, data)], memory_kind=memory_kind),
        getattr(converters, converter),
        {"max_output_bytes": expected.nbytes},
        image_sink(),
        device_outputs=("converter",),  # a host output takes no device binding
    )

    # Key assertion: the run fails, with an error that says what to change.
    assert session.termination == hs.RunTermination.FAILED
    summary = session.summary()
    assert f"{converter} takes frames in CUDA device memory" in summary, summary
    assert 'memory_kind="device"' in summary, summary


def test_raw10_unpack_rejects_a_pitch_narrower_than_the_width():
    descriptor, data, expected = raw10_frame(width=10, height=4, pitch=8)
    sink = image_sink()
    session = run(
        frame_source([(descriptor, data)]),
        converters.Raw10UnpackOp,
        {"max_output_bytes": expected.nbytes},
        sink,
    )
    assert session.termination == hs.RunTermination.FAILED
    assert "row pitch does not match the width" in session.summary()


# --------------------------------------------------------------------------------------------
# Nv12ToRgbOp
# --------------------------------------------------------------------------------------------


def nv12_frame(width=8, height=6, luma_pitch=16, chroma_pitch=12, seed=1):
    """An NV12 frame with padded rows and a gap between its planes, and its expected RGB."""
    chroma_offset = luma_pitch * height + 32
    data = np.random.default_rng(seed).integers(
        0, 256, chroma_offset + chroma_pitch * height // 2, dtype=np.uint8
    )
    descriptor = hs.schema.Image(
        width=width,
        height=height,
        encoding=ImageEncoding.NV12,
        plane_layouts=[
            ImagePlaneLayout(
                offset_bytes=0,
                row_stride_bytes=luma_pitch,
                size_bytes=luma_pitch * height,
            ),
            ImagePlaneLayout(
                offset_bytes=chroma_offset,
                row_stride_bytes=chroma_pitch,
                size_bytes=chroma_pitch * height // 2,
            ),
        ],
        exposure_time_ns=1000,
    )
    luma = (
        data[: luma_pitch * height]
        .reshape(height, luma_pitch)[:, :width]
        .astype(np.float64)
    )
    chroma = data[chroma_offset:].reshape(height // 2, chroma_pitch)[:, :width]
    chroma = chroma.reshape(height // 2, width // 2, 2).astype(np.float64) - 128.0
    cb = chroma[..., 0].repeat(2, axis=0).repeat(2, axis=1)
    cr = chroma[..., 1].repeat(2, axis=0).repeat(2, axis=1)
    rgb = np.stack(
        [luma + 1.5748 * cr, luma - 0.1873 * cb - 0.4681 * cr, luma + 1.8556 * cb],
        axis=-1,
    )
    return descriptor, data, np.clip(np.floor(rgb + 0.5), 0, 255)


def test_nv12_to_rgb_matches_bt709_full_range():
    descriptor, data, expected = nv12_frame()
    sink = image_sink()
    session = run(
        frame_source([(descriptor, data)]),
        converters.Nv12ToRgbOp,
        {"max_output_bytes": expected.size},
        sink,
    )
    assert session.termination != hs.RunTermination.FAILED, session.summary()

    # Key assertion: BT.709 full-range RGB, from the chroma pair each 2x2 block shares.
    assert len(sink.received) == 1, session.summary()
    image, rgb, source_clock_id, frame_id = sink.received[0]
    assert rgb.shape == (6, 8, 3)
    np.testing.assert_allclose(rgb, expected, atol=1)
    assert image.encoding == ImageEncoding.RGB8
    assert (image.width, image.height, image.plane_layouts) == (8, 6, [])
    assert image.exposure_time_ns == 1000
    assert source_clock_id != 0 and frame_id == 1


def test_nv12_to_rgb_leaves_a_frame_without_a_capture_time_unstamped():
    # Key setup: a frame without a capture time.
    descriptor, data, expected = nv12_frame()
    sink = image_sink()
    session = run(
        frame_source([(descriptor, data)], unstamped=(0,)),
        converters.Nv12ToRgbOp,
        {"max_output_bytes": expected.size},
        sink,
    )
    assert session.termination != hs.RunTermination.FAILED, session.summary()

    # Key assertion: the RGB frame has no capture time either, and keeps the frame id.
    assert len(sink.received) == 1, session.summary()
    _, _, source_clock_id, frame_id = sink.received[0]
    assert source_clock_id == 0 and frame_id == 1


def test_nv12_to_rgb_keeps_each_frames_capture_time():
    # Key setup: frames captured 50 ms before their publication, every 20 ms, and a second frame
    # without a capture time.
    descriptor, data, expected = nv12_frame()
    sink = image_sink()
    source = frame_source(
        [(descriptor, data)] * 6, unstamped=(1,), latency_ms=50, period_ms=20
    )
    session = run(
        source,
        converters.Nv12ToRgbOp,
        {"max_output_bytes": expected.size},
        sink,
    )
    assert session.termination != hs.RunTermination.FAILED, session.summary()

    # Key assertion: the converter publishes every frame with its own capture time, and the
    # unstamped one without any.
    assert len(sink.capture_times) == 6, session.summary()
    assert sink.capture_times == source.capture_times
    assert sink.capture_times[1] is None


def test_nv12_to_rgb_drops_frames_while_its_pool_is_exhausted():
    # Key setup: a consumer that keeps every frame it receives, so that the converter's output
    # pool runs out after a few frames. (The run does not end while the consumer holds them.)
    descriptor, data, expected = nv12_frame()
    source, sink = frame_source([(descriptor, data)] * 20), image_sink(retain=True)
    session = run(
        source,
        converters.Nv12ToRgbOp,
        {"max_output_bytes": expected.size},
        sink,
        until=lambda: source.published == 20 and len(sink.received) > 0,
    )

    # Key assertion: the converter drops the frames it has no buffer for, and the run goes on.
    assert session.termination != hs.RunTermination.FAILED, session.summary()
    assert 0 < len(sink.received) < 20


def test_compile_kernels_needs_no_frame():
    converters.compile_kernels()


def test_derive_from_keeps_an_absent_capture_time_absent():
    # derive_from() runs inside an operator; here, on the metadata of a real sample.
    class Source(hs.Operator):
        output = hs.Output("output", hs.payload.uint32)

        def setup(self, spec):
            spec.output(self.output)

        def contract(self):
            return (
                hs.Contract()
                .trigger(hs.OnClock(period=hs.time.ms(1)))
                .complete_after(1)
            )

        def compute(self, context):
            self.output.emit(1, options=hs.EmitOptions(frame_id=7))

    class Sink(hs.Operator):
        input = hs.Input("input", hs.payload.uint32)
        options = None

        def setup(self, spec):
            spec.input(self.input)

        def contract(self):
            return hs.Contract().trigger(hs.OnEach(self.input))

        def compute(self, context):
            metadata = self.input.receive().metadata
            type(self).options = converters.derive_from(metadata)

    graph = hs.Graph("derive_from_test", default_clock=hs.RealtimeClock)
    source = graph.op(Source, "source")
    sink = graph.op(Sink, "sink")
    graph.add_flow(source.output, sink.input)
    plan = hs.compile(graph)
    assert plan.ok, [str(diagnostic) for diagnostic in plan.diagnostics]
    hs.run(plan)
    assert Sink.options.frame_id == 7
    assert Sink.options.capture_time is None
