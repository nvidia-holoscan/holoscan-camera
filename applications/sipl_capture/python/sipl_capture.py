# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture SIPL camera frames and their metadata in an SDK 5 Python graph."""

import argparse
import math

import holoscan as hs
from holoscan.schema import Image
from holoscan_camera import SIPLCaptureService
from holoscan_camera.operators import SIPLCaptureOp
from holoscan_camera.schema import SIPLFrameMetadata


class FramePrinter(hs.Operator):
    """Report one camera's frames without converting their pixels."""

    frame = hs.Input("frame", Image)
    camera = hs.Param("camera")

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
                f"{self.camera}: frame {self.received}: {image.width}x{image.height}, "
                f"sequence={image.header.device_sequence}"
            )


class MetadataPrinter(hs.Operator):
    """Count one camera's metadata records, logging each one's HSB and SIPL metadata with
    `print_metadata`, and stop the run at the `frame_limit`-th (0: never)."""

    metadata = hs.Input("metadata", SIPLFrameMetadata)
    camera = hs.Param("camera")
    print_metadata = hs.Param(False)
    frame_limit = hs.Param(0)

    def setup(self, spec):
        spec.input(self.metadata, queue_depth=4)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.metadata))

    def start(self):
        self.received = 0

    def compute(self, context):
        # A record carries the ISP statistics, about 400 KB; a selected sample converts it to
        # Python only when its data is read, to print it.
        sample = self.metadata.selected_sample()
        if self.print_metadata:
            log_metadata(self.camera, sample.data)
        self.received += 1
        if self.received == self.frame_limit:
            context.request_stop()


def log_metadata(camera, record):
    """Log one record's HSB and SIPL metadata, in the C++ sipl_player's format."""
    if record.hsb_valid:
        print(
            f"[{camera}] frame={record.hsb_frame_number}, "
            f"ts={record.hsb_timestamp_s}.{record.hsb_timestamp_ns:09}, "
            f"meta_ts={record.hsb_metadata_s}.{record.hsb_metadata_ns:09}, "
            f"crc=0x{record.hsb_crc:08x}, bytes={record.hsb_bytes_written}"
        )
    else:
        print(f"[{camera}] (no HSB metadata)")
    print(f"    SIPL Metadata: start time={record.frame_capture_start_tsc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera-config",
        default="",
        help="SIPL configuration name (default: the first found)",
    )
    parser.add_argument(
        "--json-config", default="", help="vendor JSON platform configuration"
    )
    parser.add_argument(
        "--cameras",
        type=int,
        help="feed the graph from the configuration's first N cameras (default: all of "
        "them; 1 with --validate, which opens no camera); the service still opens and "
        "streams every camera of the configuration",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="publish the sensor's RAW frames, not the ISP's NV12",
    )
    parser.add_argument(
        "--memory-kind", choices=("device", "pinned", "host"), default="device"
    )
    parser.add_argument(
        "--frames", type=int, default=120, help="stop after this many frames"
    )
    parser.add_argument(
        "--print-metadata", action="store_true", help="log each frame's SIPL metadata"
    )
    parser.add_argument("--run-timeout", type=float, default=30.0)
    parser.add_argument("--list-configs", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.cameras is not None and args.cameras <= 0:
        parser.error("--cameras must be positive")
    if not math.isfinite(args.run_timeout) or args.run_timeout <= 0:
        parser.error("--run-timeout must be finite and positive")
    if args.list_configs:
        SIPLCaptureService.list_available_configs(args.json_config)
        return

    # The cameras of one configuration share its service. Constructing it opens no camera;
    # asking for its cameras initializes NvSIPL, which opens them.
    service = SIPLCaptureService(
        camera_config=args.camera_config,
        json_config=args.json_config,
        raw_output=args.raw,
    )
    cameras = args.cameras
    if cameras is None:
        cameras = 1 if args.validate else len(service.get_camera_info())
        if cameras == 0:
            raise RuntimeError("the SIPL configuration has no cameras")

    graph = hs.Graph("sipl-python", default_clock=hs.RealtimeClock)
    options = hs.CompileOptions()
    for index in range(cameras):
        name = f"camera{index}"
        camera = graph.op(
            SIPLCaptureOp,
            name,
            service=service,
            camera_index=index,
            memory_kind=args.memory_kind,
        )
        frames = graph.op(FramePrinter, f"frames{index}", camera=name)
        metadata = graph.op(
            MetadataPrinter,
            f"metadata{index}",
            camera=name,
            print_metadata=args.print_metadata,
            frame_limit=args.frames,
        )
        graph.add_flow(camera.frame, frames.frame, queue_depth=2)
        graph.add_flow(camera.sensor_data, metadata.metadata, queue_depth=4)
        if args.memory_kind == "device":
            # Device frames need an explicit GPU binding.
            options.deployment.bind_tensor_output_device(
                operator_path=name, output_port="frame", device=hs.execution.DeviceId(0)
            )
    plan = hs.compile(graph, options)
    if not plan.ok:
        raise RuntimeError(plan.json())
    if args.validate:
        print("SIPL Python graph validation complete")
        return
    # Python runs use caller-managed signals. The context stops and joins capture on timeout,
    # an exception, or Ctrl-C. The first camera to deliver --frames frames stops the run.
    with hs.run_async(plan) as session:
        if not session.wait(timeout=args.run_timeout):
            raise TimeoutError("SIPL capture exceeded --run-timeout")
        if session.termination == hs.RunTermination.FAILED:
            raise RuntimeError(session.summary())
    print("SIPL Python capture finished")


if __name__ == "__main__":
    main()
