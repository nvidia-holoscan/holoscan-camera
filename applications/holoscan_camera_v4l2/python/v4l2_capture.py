# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Receive native V4L2 YUYV images in a Python operator."""

import argparse
import math

import holoscan as hs
from holoscan.schema import Image
from holoscan.schema.image import ImageEncoding
from holoscan_camera.operators import V4l2CaptureOp

# Preview-only dependencies: holoscan_visualization.operators and numpy.
# Imported inside add_preview() and YuyvPreviewOp.compute() so capture and
# validation can run without either package.


class FrameCounterOp(hs.Operator):
    """Consume camera frames to demonstrate Python delivery and limit the sample run.

    Input ``image`` accepts Image messages and triggers compute on each arrival.
    Parameter ``count`` defaults to 120 received frames; 0 disables the frame limit.
    Log the first frame and every 30th frame; this sink has no output port.
    """

    image = hs.Input("image", Image)
    count = hs.Param(120)

    def setup(self, spec):
        spec.input(self.image)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.image))

    def start(self):
        self.received = 0

    def compute(self, context):
        image = self.image.receive_data()
        self.received += 1
        if self.received == 1 or self.received % 30 == 0:
            print(
                f"frame {self.received}: {image.width}x{image.height} "
                f"encoding={image.encoding}, bytes={image.data.nbytes}",
                flush=True,
            )
        if self.count > 0 and self.received >= self.count:
            context.request_completion()


class YuyvPreviewOp(hs.Operator):
    """Adapt the Camera byte-row layout to Holoviz's packed YUYV pixel layout.

    Input ``image`` and output ``frame`` carry Image messages. ``width`` and
    ``height`` default to 640 and 480 and bound the host output pool. Each input
    becomes a uint8 tensor shaped (height, width, 2), preserving pixel bytes and
    sample metadata. This preview adapter requires host-accessible input memory.
    """

    image = hs.Input("image", Image)
    frame = hs.Output("frame", Image)
    width = hs.Param(640)
    height = hs.Param(480)

    def setup(self, spec):
        spec.input(self.image)
        spec.output(self.frame).produces_tensor(
            hs.tensor.OutputSpec(
                storage="runtime_pool",
                memory_kind=hs.tensor.MemoryKind.HOST,
                dtype="uint8",
                rank=3,
                transfer=hs.tensor.TensorTransferPolicy(
                    foreign_emit_policy=hs.tensor.InterfaceTensorEmitPolicy.COPY_IF_NEEDED
                ),
            ),
            hs.tensor.byte_span(self.width * self.height * 2),
            field="data",
        )

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.image))

    def compute(self, context):
        import numpy as np

        sample = self.image.receive()
        image = sample.data
        if image.encoding != ImageEncoding.YUYV or (image.width, image.height) != (
            self.width,
            self.height,
        ):
            raise ValueError(
                "Preview requires YUYV images at the configured dimensions"
            )
        # Holoviz requires HWC for YUYV; Camera's public payload remains byte rows.
        # NumPy's borrowed view is read-only; make an owned copy for DLPack export.
        # The SDK then copies it into the declared output pool on forward.
        pixels = np.from_dlpack(image.data).reshape(self.height, self.width, 2).copy()
        image.data = hs.Tensor.as_tensor(pixels)
        self.frame.forward(sample, image)


def add_preview(graph, camera, width, height, yuv_model, yuv_range):
    """Display YUYV images through SDK operators and bounded SDK queues."""
    from holoscan_visualization.operators import (
        HolovizOp,
        ImageFormat,
        ImageLayer,
        LayerTrigger,
        WindowSink,
    )

    adapter = graph.op(YuyvPreviewOp, "preview_layout", width=width, height=height)
    visualizer = HolovizOp(
        graph,
        "holoviz",
        layers=[
            ImageLayer(
                port_name="video",
                format=ImageFormat.YUYV422,
                max_width=width,
                max_height=height,
                yuv_model=yuv_model,
                yuv_range=yuv_range,
            )
        ],
        sink=WindowSink(
            title="Holoscan V4L2 preview",
            width=width,
            height=height,
            close_on_escape=True,
        ),
        trigger=LayerTrigger(layer=0),
    )
    # A slow display replaces waiting preview frames without backpressuring capture.
    for source, target in (
        (camera.frame, adapter.image),
        (adapter.frame, visualizer.video),
    ):
        graph.add_flow(
            source, target, queue_policy=hs.QueuePolicy.DROP_OLDEST, queue_depth=1
        )
    graph.partition("display").add(visualizer)
    graph.auto_partition_remaining()


def run_capture(plan, timeout):
    # Context exit stops and joins the native capture worker on timeout or Ctrl-C.
    with hs.run_async(plan) as session:
        if not session.wait(timeout=timeout or None):
            raise TimeoutError("V4L2 capture exceeded --timeout")
        if session.termination == hs.RunTermination.FAILED:
            raise RuntimeError(session.summary())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--frame-id", default="camera_optical_frame")
    parser.add_argument(
        "--memory-kind", choices=("host", "pinned", "device"), default="host"
    )
    parser.add_argument("--cuda-device", type=int, default=0)
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Capture deadline in seconds; 0 disables it for continuous preview",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=120,
        help="Frame limit; 0 runs until preview closes",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Display captured frames using Holoscan Visualization",
    )
    parser.add_argument(
        "--yuv-model", choices=("bt601", "bt709", "bt2020"), default="bt601"
    )
    parser.add_argument("--yuv-range", choices=("limited", "full"), default="limited")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.frames < 0 or (args.frames == 0 and not args.preview):
        parser.error("--frames must be positive, or zero with --preview")
    if (
        not math.isfinite(args.timeout)
        or args.timeout < 0
        or (args.timeout == 0 and not (args.preview and args.frames == 0))
    ):
        parser.error(
            "--timeout must be finite and positive, or zero for continuous preview"
        )
    if args.cuda_device < 0:
        parser.error("--cuda-device must be nonnegative")
    if args.preview and args.memory_kind == "device":
        parser.error("--preview requires --memory-kind host or pinned for NumPy access")

    graph = hs.Graph("v4l2-python", default_clock=hs.RealtimeClock)
    camera = graph.op(
        V4l2CaptureOp,
        "camera",
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        frame_id=args.frame_id,
        memory_kind=args.memory_kind,
    )
    counter = graph.op(FrameCounterOp, "counter", count=args.frames)
    if args.preview:
        # All camera fanout edges must tolerate a slow preview startup/consumer.
        # The counter measures received frames, not every camera exposure.
        graph.add_flow(
            camera.frame,
            counter.image,
            queue_policy=hs.QueuePolicy.DROP_OLDEST,
            queue_depth=1,
        )
        add_preview(
            graph, camera, args.width, args.height, args.yuv_model, args.yuv_range
        )
    else:
        graph.add_flow(camera.frame, counter.image)
    options = hs.CompileOptions()
    if args.memory_kind == "device":
        options.deployment.bind_tensor_output_device(
            operator_path="camera",
            output_port="frame",
            device=hs.execution.DeviceId(args.cuda_device),
        )
    plan = hs.compile(graph, options)
    if not plan.ok:
        raise RuntimeError(plan.json())
    if args.validate:
        print("V4L2 Python graph validation complete")
        return
    if args.preview:
        print(
            "Live preview: close the window or press Escape to stop capture.",
            flush=True,
        )
    try:
        run_capture(plan, args.timeout)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
