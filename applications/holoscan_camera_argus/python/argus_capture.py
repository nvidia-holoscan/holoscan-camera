# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture Argus images and typed metadata in a Holoscan Python graph."""

import argparse
import math

import holoscan as hs
from holoscan.schema import Image
from holoscan_camera.operators import ArgusCaptureOp
from holoscan_camera.schema import ArgusFrameMetadata


class FramePrinter(hs.Operator):
    """Inspect the packed rank-1 image tensor without converting its pixels."""

    frame = hs.Input("frame", Image)

    def setup(self, spec):
        spec.input(self.frame)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.frame))

    def start(self):
        self.received = 0

    def compute(self, context):
        image = self.frame.receive_data()
        self.received += 1
        if self.received == 1 or self.received % 30 == 0:
            print(
                f"frame {self.received}: {image.width}x{image.height}, "
                f"sequence={image.header.device_sequence}, bytes={image.data.nbytes}"
            )


class MetadataPrinter(hs.Operator):
    """Stop after the requested number of metadata samples, as in the C++ sample."""

    metadata = hs.Input("metadata", ArgusFrameMetadata)
    count = hs.Param(120)

    def setup(self, spec):
        spec.input(self.metadata)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.metadata))

    def start(self):
        self.received = 0

    def compute(self, context):
        data = self.metadata.receive_data()
        self.received += 1
        if self.received == 1 or self.received % 30 == 0:
            print(
                f"metadata: camera={data.camera_index}, sequence={data.sequence}, "
                f"SOF(ns)={data.sensor_sof_timestamp_ns}, exposure(ns)={data.exposure_time_ns}, "
                f"queue drops={data.queue_drops}, publication drops={data.publication_drops}"
            )
        if self.received >= self.count:
            context.request_completion()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--mode", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--format", choices=("nv12", "i420"), default="nv12")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--run-timeout", type=float, default=30.0)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if not math.isfinite(args.run_timeout) or args.run_timeout <= 0:
        parser.error("--run-timeout must be finite and positive")

    graph = hs.Graph("argus-python", default_clock=hs.RealtimeClock)
    camera = graph.op(
        ArgusCaptureOp,
        "camera",
        camera_index=args.camera,
        sensor_mode=args.mode,
        width=args.width,
        height=args.height,
        fps=args.fps,
        pixel_format=args.format,
        memory_kind="host",
    )
    frames = graph.op(FramePrinter, "frames")
    metadata = graph.op(MetadataPrinter, "metadata", count=args.frames)
    graph.add_flow(camera.frame, frames.frame, queue_depth=2)
    graph.add_flow(camera.metadata, metadata.metadata, queue_depth=2)
    plan = hs.compile(graph)
    if not plan.ok:
        raise RuntimeError(plan.json())
    if args.validate:
        print("Argus Python graph validation complete")
        return
    # Python runs use caller-managed signals. The context stops and joins capture
    # on timeout, an exception, or Ctrl-C, returning native buffers through C++ cleanup.
    with hs.run_async(plan) as session:
        if not session.wait(timeout=args.run_timeout):
            raise TimeoutError("Argus capture exceeded --run-timeout")
        if session.termination == hs.RunTermination.FAILED:
            raise RuntimeError(session.summary())
    print("Argus Python capture finished")


if __name__ == "__main__":
    main()
