# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Opt-in capture test for a camera supporting 640x480 YUYV at 30 FPS."""

import os

import pytest

import holoscan as hs
from holoscan.schema import Image
from holoscan.schema.image import ImageEncoding
from holoscan_camera.operators import V4l2CaptureOp

DEVICE = os.environ.get("HOLOSCAN_CAMERA_TEST_DEVICE")
pytestmark = pytest.mark.skipif(
    not DEVICE, reason="Set HOLOSCAN_CAMERA_TEST_DEVICE to enable live camera capture"
)


def test_capture_tensor_access_and_camera_release():
    import numpy as np

    # Repeat in one process to exercise native shutdown and reopening the device.
    for attempt in range(2):
        sequences = []

        class InspectFrames(hs.Operator):
            image = hs.Input("image", Image)

            def setup(self, spec):
                spec.input(self.image)

            def contract(self):
                return hs.Contract().trigger(hs.OnEach(self.image))

            def compute(self, context):
                image = self.image.receive_data()
                assert (image.width, image.height) == (640, 480)
                assert image.encoding == ImageEncoding.YUYV
                assert image.header.frame_id == "python_test_camera"
                pixels = np.from_dlpack(image.data)
                assert pixels.shape == (480, 1280)
                assert pixels.dtype == np.uint8
                assert pixels.nbytes == 614400
                # Read the backing memory while the received image owns the tensor.
                assert np.array_equal(pixels.copy(), pixels)
                sequences.append(image.header.device_sequence)
                if len(sequences) >= 60:
                    context.request_completion()

        graph = hs.Graph(
            f"v4l2-python-hardware-{attempt}", default_clock=hs.RealtimeClock
        )
        camera = graph.op(
            V4l2CaptureOp,
            "camera",
            device=DEVICE,
            width=640,
            height=480,
            fps=30,
            frame_id="python_test_camera",
            memory_kind="host",
        )
        consumer = graph.op(InspectFrames, "inspect")
        graph.add_flow(camera.frame, consumer.image)
        plan = hs.compile(graph)
        assert plan.ok, plan.json()
        with hs.run_async(plan) as session:
            assert session.wait(timeout=20.0), (
                "Capture did not finish within 20 seconds"
            )
            assert not session.diagnostics, session.diagnostics
            assert session.termination == hs.RunTermination.REQUESTED_COMPLETED
        assert len(sequences) == 60
        assert all(
            current > previous for previous, current in zip(sequences, sequences[1:])
        )
