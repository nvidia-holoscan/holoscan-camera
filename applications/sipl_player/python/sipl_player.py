# SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# sipl_player.py -- shows live video from every camera of an NvSIPL camera configuration in a
# HoloViz window. The Python version of ../cpp/sipl_player.cpp, and a Holoscan SDK 5 port of
# Holoscan Sensor Bridge's examples/sipl_player.py.
#
# By default SIPL's ISP processes the frames and SIPLCaptureOp publishes NV12, which HoloViz
# converts and draws:
#
#   SIPLCaptureOp (NV12) -> HolovizOp
#
# With --raw, SIPL delivers the sensor's RAW10 Bayer data instead, which holoscan_camera's
# Raw10UnpackOp unpacks with a CuPy kernel and BayerDemosaicOp demosaics on the GPU:
#
#   SIPLCaptureOp (RAW10) -> Raw10UnpackOp -> BayerDemosaicOp -> HolovizOp
#
# All cameras share one SIPLCaptureService and are tiled left to right in one window. (The C++
# player's --separate, one window per camera, is not available here: its windows share a
# serialization domain, which a Python graph cannot declare for HolovizOp.)
#
# Usage:
#   sipl_player.py --json-config applications/config/sipl/vb1940_dual.json
#   sipl_player.py --list-configs

import argparse
import math
import signal
import sys
import warnings

import holoscan as hs
import holoscan_vision as hv
import holoscan_visualization as hz  # noqa: F401 -- registers "holoscan.visualization.HolovizOp"
from holoscan.schema.image import ImageEncoding

import holoscan_camera as hc
from holoscan_camera.operators import SIPLCaptureOp
from holoscan_camera.operators.converters import Raw10UnpackOp, compile_kernels
from holoscan_camera.schema import SIPLFrameMetadata

# The SDK's CUDA stream context for CuPy uses CuPy's deprecated ExternalStream.
warnings.filterwarnings(
    "ignore", message="ExternalStream is deprecated", category=DeprecationWarning
)

# HolovizOp's limit on layers, so on the cameras one window shows.
_MAX_LAYERS = 8
# How long another camera's layer shows its last frame when no new one arrives. The window renders
# only while every layer has a frame, so another camera that stops would otherwise stop the window,
# and the handling of its events, after HoloViz's default 100 ms. (When the first camera stops,
# so does the window.)
_MAX_FRAME_AGE_NS = 3600 * 10**9

_BAYER_ENCODINGS = {
    hc.BayerFormat.BGGR: ImageEncoding.BAYER_BGGR,
    hc.BayerFormat.RGGB: ImageEncoding.BAYER_RGGB,
    hc.BayerFormat.GBRG: ImageEncoding.BAYER_GBRG,
    hc.BayerFormat.GRBG: ImageEncoding.BAYER_GRBG,
}


class DiscardImageOp(hs.Operator):
    """With --headless, HolovizOp renders into a CUDA image on its output instead of a window;
    the output must be consumed, and this drops each rendered frame."""

    input = hs.Input("input", hs.schema.Image)

    def setup(self, spec):
        spec.input(self.input, queue_depth=1)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context):
        self.input.receive_data()


class SensorDataSinkOp(hs.Operator):
    """Drains a camera's metadata records, logging each one's HSB and SIPL metadata with
    `print_metadata`, and stops the run at the `frame_limit`-th (0: never)."""

    input = hs.Input("input", SIPLFrameMetadata)
    camera_name = hs.Param("camera")
    print_metadata = hs.Param(False)
    frame_limit = hs.Param(0)

    def setup(self, spec):
        spec.input(self.input, queue_depth=4)

    def contract(self):
        return hs.Contract().trigger(hs.OnEach(self.input))

    def start(self):
        self.received = 0

    def compute(self, context):
        # A record carries the ISP statistics, about 400 KB; a selected sample converts it to
        # Python only when its data is read, to print it.
        sample = self.input.selected_sample()
        if self.print_metadata:
            log_metadata(self.camera_name, sample.data)
        self.received += 1
        if self.received == self.frame_limit:
            context.request_stop()


def log_metadata(camera, record):
    """Logs one record's HSB and SIPL metadata, in the C++ player's format."""
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


def add_camera(graph, name, service, index):
    """Adds the SIPLCaptureOp of the service's camera `index`. Its frames stay on the GPU, the
    operator's default, which needs the device binding compile_player() gives them."""
    return graph.op(SIPLCaptureOp, name, service=service, camera_index=index)


def placeholder_cameras():
    """--validate's stand-in for the camera configuration: querying the real one initializes
    NvSIPL, which opens the cameras."""
    cameras = []
    for index in range(2):
        info = hc.CameraInfo()
        info.output_name = f"camera{index}"
        info.width = 1920
        info.height = 1080
        info.bytes_per_line = 2560
        cameras.append(info)
    return cameras


def compile_player(graph, args, service, cameras):
    """Builds and compiles the player's graph: every camera in `cameras` (the service's camera
    list), tiled left to right in one window."""
    if len(cameras) > _MAX_LAYERS:
        raise ValueError(
            f"one window shows at most {_MAX_LAYERS} cameras, the configuration has {len(cameras)}"
        )
    options = hs.CompileOptions()

    def bind_device(operator_path, output_port):
        options.deployment.bind_tensor_output_device(
            operator_path=operator_path,
            output_port=output_port,
            device=hs.execution.DeviceId(args.cuda_device),
        )

    # Every edge from a camera is a freshest-frame mailbox: SIPLCaptureOp must never find a full
    # queue, and the display skips to the latest frame when it falls behind.
    mailbox = {"queue_policy": hs.QueuePolicy.DROP_OLDEST, "queue_depth": 1}
    # The window renders each frame of the first camera as it arrives, with frames of the other
    # cameras captured no later than it: for cameras that capture together, usually the ones
    # before. Keep two of theirs, so that a frame captured a moment after the first camera's
    # cannot push out the one before it and leave the layer with nothing to show.
    side_layer = {"queue_policy": hs.QueuePolicy.DROP_OLDEST, "queue_depth": 2}

    # Window size: the tiled cameras at their native aspect ratio, scaled down to fit 1920x1080
    # (rounded half up, as the C++ player's lround does).
    total_width = sum(info.width for info in cameras)
    max_height = max(info.height for info in cameras)
    if total_width == 0 or max_height == 0:
        raise ValueError("the camera configuration reports an empty frame size")
    scale = min(1.0, 1920 / total_width, 1080 / max_height)
    width = math.floor(total_width * scale + 0.5)
    height = math.floor(max_height * scale + 0.5)

    layers = []
    left = 0
    for index, info in enumerate(cameras):
        layer = {
            "port_name": f"camera{index}",
            "kind": "image",
            "format": "rgba16_unorm" if args.raw else "nv12",
            "max_width": info.width,
            "max_height": info.height,
        }
        if not args.raw:
            # SIPLCaptureService allocates the ISP output as NvSciColorStd_REC709_ER: BT.709,
            # full range.
            layer["yuv_model"] = "bt709"
            layer["yuv_range"] = "full"
        if len(cameras) > 1:
            layer["view"] = {
                "offset_x": left / total_width,
                "offset_y": 0.0,
                "scale_x": info.width / total_width,
                "scale_y": info.height / max_height,
            }
        left += info.width
        layers.append(layer)

    if args.headless:
        sink = {"kind": "cuda", "width": width, "height": height}
        bind_device("holoviz", "output")
    else:
        sink = {
            "kind": "window",
            "title": "SIPL Player",
            # Fullscreen keeps the monitor's current mode; a size would switch it to the closest
            # one.
            "width": 0 if args.fullscreen else width,
            "height": 0 if args.fullscreen else height,
            "fullscreen": args.fullscreen,
            "close_on_escape": True,
            # The demosaiced RAW is linear sensor data: encode it to sRGB on write. The ISP's
            # NV12 is already display-encoded.
            "framebuffer_srgb": args.raw,
        }
    viz = graph.op(
        "holoscan.visualization.HolovizOp",
        "holoviz",
        layers=layers,
        sink=sink,
        # Render one frame per frame of the first camera.
        trigger={"kind": "layer", "layer": 0},
        max_input_age_ns=_MAX_FRAME_AGE_NS,
    )

    for index, info in enumerate(cameras):
        to_display = mailbox if index == 0 else side_layer
        camera = add_camera(graph, f"camera{index}", service, index)
        bind_device(f"camera{index}", "frame")

        # Drains the camera's metadata records; prints them with --metadata. The first camera's
        # also ends the run at --frame-limit.
        sensor_data = graph.op(
            SensorDataSinkOp,
            f"sensor_data{index}",
            camera_name=info.output_name,
            print_metadata=args.metadata,
            frame_limit=args.frame_limit if index == 0 else 0,
        )
        graph.add_flow(
            camera.sensor_data,
            sensor_data.input,
            queue_policy=hs.QueuePolicy.DROP_OLDEST,
            queue_depth=4,
        )

        if not args.raw:
            graph.add_flow(camera.frame, viz[f"camera{index}"], **to_display)
            continue
        unpack = graph.op(
            Raw10UnpackOp,
            f"unpack{index}",
            max_output_bytes=info.width * info.height * 2,
            bayer_encoding=_BAYER_ENCODINGS[info.bayer_format].name,
        )
        bind_device(f"unpack{index}", "output")
        demosaic = graph.op(
            hv.operators.BayerDemosaicOp,
            f"demosaic{index}",
            bayer_grid_pos=info.bayer_format.name.lower(),
            # HoloViz's rgba16_unorm layer takes RGBA: generate an opaque alpha channel.
            generate_alpha=True,
            alpha_value=65535,
        )
        bind_device(f"demosaic{index}", "output")
        graph.add_flow(camera.frame, unpack.input, **mailbox)
        graph.add_flow(unpack.output, demosaic.input, **mailbox)
        graph.add_flow(demosaic.output, viz[f"camera{index}"], **to_display)

    if args.headless:
        discard = graph.op(DiscardImageOp, "discard")
        graph.add_flow(viz.output, discard.input, **mailbox)

    graph.set_default_clock(graph.add_clock(hs.RealtimeClock, "clock"))
    return hs.compile(graph, options)


def run_player(args):
    # Constructing the service does not touch NvSIPL; get_camera_info() initializes it.
    service = hc.SIPLCaptureService(
        camera_config=args.camera_config,
        json_config=args.json_config,
        raw_output=args.raw,
        cuda_device=args.cuda_device,
    )
    cameras = placeholder_cameras() if args.validate else service.get_camera_info()
    if not cameras:
        print("sipl_player: the camera configuration has no cameras", file=sys.stderr)
        return 1

    graph = hs.Graph("sipl_player")
    try:
        plan = compile_player(graph, args, service, cameras)
    except ValueError as error:
        print(f"sipl_player: {error}", file=sys.stderr)
        return 1
    if not plan.ok:
        print("Graph compilation failed:", file=sys.stderr)
        for diagnostic in plan.diagnostics:
            print(f"  {diagnostic}", file=sys.stderr)
        return 1
    if args.validate:
        print(
            f"graph validation complete ({'raw' if args.raw else 'isp'}, tiled"
            f"{', headless' if args.headless else ''})"
        )
        return 0

    for info in cameras:
        print(
            f"Camera {info.output_name}: {info.width}x{info.height}"
            f"{' RAW10' if args.raw else ' ISP (NV12)'}"
        )
    if args.raw:
        compile_kernels()  # rather than while the first frame waits
    # Runs until the session ends (the window closed, --frame-limit, or a failure).
    with hs.run_async(plan) as session:
        try:
            session.wait()
        except KeyboardInterrupt:
            # Ctrl+C or SIGTERM: leaving the block stops the session cooperatively, which stops
            # the cameras. A second one ends the process at once.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            print("Stopping...")
    if session.diagnostics:
        print(session.summary(), file=sys.stderr)
    return 1 if session.termination == hs.RunTermination.FAILED else 0


def main():
    # Like Ctrl+C, SIGTERM (kill, docker stop) raises KeyboardInterrupt, so the session stops
    # cooperatively and the cameras are stopped on the way out.
    signal.signal(signal.SIGTERM, signal.default_int_handler)

    parser = argparse.ArgumentParser(
        description="Show live video from every camera of an NvSIPL camera configuration."
    )
    parser.add_argument(
        "--camera-config",
        default="",
        help="SIPL camera configuration name (default: the first one found in the SIPL "
        "database or --json-config)",
    )
    parser.add_argument("--json-config", default="", help="Vendor JSON platform config")
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List the available camera configurations and exit",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Capture RAW10 and unpack and demosaic it on the GPU, instead of showing SIPL's "
        "ISP output",
    )
    parser.add_argument(
        "--frame-limit",
        type=int,
        default=0,
        help="Stop after N frames from the first camera (default: 0, run until the window "
        "closes or Ctrl+C)",
    )
    parser.add_argument(
        "--metadata", action="store_true", help="Print each frame's metadata"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Render into a CUDA image instead of a window",
    )
    parser.add_argument(
        "--fullscreen", action="store_true", help="Run in fullscreen mode"
    )
    parser.add_argument(
        "--cuda-device",
        type=int,
        default=0,
        help="CUDA device ordinal (default: 0); with a window, it must be the GPU that drives "
        "the display",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Compile the graph for two placeholder 1920x1080 cameras and exit, without "
        "opening a camera",
    )
    args = parser.parse_args()
    if args.frame_limit < 0 or args.cuda_device < 0:
        parser.error("--frame-limit and --cuda-device must be non-negative")
    if args.cuda_device > 2**31 - 1:
        parser.error("--cuda-device must fit a 32-bit CUDA device ordinal")

    if args.list_configs:
        hc.SIPLCaptureService.list_available_configs(args.json_config)
        return 0
    return run_player(args)


if __name__ == "__main__":
    sys.exit(main())
