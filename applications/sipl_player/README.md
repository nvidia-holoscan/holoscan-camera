# SIPL Camera Viewer Example

Shows live video from every camera of an NvSIPL camera configuration in a
HoloViz window, through [sipl_capture_op](../../operators/sipl_capture_op).
It also has a [Python version](#python-version).

By default, SIPL's ISP processes the frames and `SIPLCaptureOp` publishes NV12
(BT.709, full range), which `HolovizOp` converts and draws:

```text
SIPLCaptureOp (NV12) -> HolovizOp
```

With `--raw`, SIPL delivers the sensor's RAW10 Bayer data instead, and the
application unpacks it on the GPU and demosaics it with the SDK's
`BayerDemosaicOp`:

```text
SIPLCaptureOp (RAW10) -> Raw10UnpackOp -> BayerDemosaicOp -> HolovizOp
```

`Raw10UnpackOp` is part of this application: it turns NvSci's
`X2Rc10Rb10Ra10` packing (three 10-bit samples per 32-bit word, which
`SIPLCaptureOp` publishes as a `CUSTOM` image) into the 16-bit Bayer mosaic
`BayerDemosaicOp` takes. No optical black or white balance correction is
applied, so `--raw` shows the sensor's uncorrected colors.

All cameras share one `SIPLCaptureService` and are tiled left to right in one
window. The window renders each frame of the first camera as it arrives, with
frames of the other cameras captured no later than it. So with cameras that
capture together, the other tiles usually lag the first by a frame. Another
camera that stops delivering frames keeps showing its last one (for up to an
hour), and the window goes on; when the first camera stops, the window stops
rendering and must be closed with "Ctrl+C".

With `--separate`, each camera gets its own window instead, which renders each
frame of its camera as it arrives, and closing any window stops the player.
All windows belong to one graph and are serviced from one lane, because
Holoscan SDK 5's HoloViz does not serialize its window-system calls across
threads.

HolovizOp matches the other cameras' frames to the first camera's by capture
time. For Holoscan Sensor Bridge cameras such as the VB1940, `SIPLCaptureOp`
takes it from the bridge's first-data timestamp, which needs host PTP; other
cameras use SIPL's capture-end time. See [SIPLCaptureOp](../../operators/sipl_capture_op/README.md#siplcaptureop).

Frames from the cameras are delivered device-resident (`kCudaDevice`), with
the matching device binding.

## Requirements

- Requires NVIDIA Jetson AGX Thor with JetPack 7.2.1, the only
  [supported SIPL platform](../../README.md#supported-platforms) in this release
- Requires one or more VB1940 cameras via Holoscan Sensor Bridge FPGA, with
  host PTP running (see [SIPLCaptureOp](../../operators/sipl_capture_op/README.md#siplcaptureop))
- Requires a display, unless run with `--headless`

Experimental source builds on IGX OS 2.0 / R38.5 are not a supported
configuration. They need the
[host SIPL development prerequisite](../../operators/sipl_capture_op/README.md#igx-r385-host-prerequisite)
before using the wrapper.

## Usage

```text
Usage:
  sipl_player [OPTIONS]

Options:
  --camera-config NAME   SIPL camera configuration name (default: the first one
                         found in the SIPL database or --json-config)
  --json-config PATH     Vendor JSON platform config
  --list-configs         List the available camera configurations and exit
  --raw                  Capture RAW10 and unpack and demosaic it on the GPU,
                         instead of showing SIPL's ISP output
  --separate             Show each camera in its own window
  --frame-limit N        Stop after N frames from every camera (default: 0, run
                         until the window closes or Ctrl+C)
  --metadata             Print each frame's metadata
  --headless             Render into a CUDA image instead of a window
  --fullscreen           Run in fullscreen mode
  --cuda-device N        CUDA device ordinal (default: 0); with a window, it must be
                         the GPU that drives the display
  --validate             Compile the graph for two placeholder 1920x1080 cameras and
                         exit, without opening a camera
  -h, --help             Show this help text
```

`--metadata` prints, per frame, the Holoscan Sensor Bridge record embedded in
the frame (frame number, timestamps, CRC, byte count), the SIPL capture-start
and end-of-frame timestamps and, in ISP mode, the first window of the ISP's
local average statistics.

`--fullscreen` keeps the monitor's current display mode.

Press Esc or close the window to stop. Ctrl+C or SIGTERM stops every session
cleanly, which stops the cameras; a second Ctrl+C ends the process at once.

The sample configs in [`applications/config/sipl`](../config/sipl) are
`vb1940_single.json` (one camera), `vb1940_dual.json` (two independent
cameras) and `vb1940_stereo.json` (two hardware-synced cameras).

## Run

```bash
./holoscan_camera run sipl_player --language cpp --run-args \
  '--json-config applications/config/sipl/vb1940_dual.json'
```

Name the language: without `--language`, the CLI runs the
[Python version](#python-version).

Set the camera MAC addresses in the JSON config to match your connected
cameras before running. The CLI launches the application from the repository
root, so a relative `--json-config` path resolves from that directory. For
container runs, the application metadata runs the container privileged: NvSIPL
reads `/proc/device-tree/model` when it loads the camera query database, which
Docker hides from unprivileged containers, and opening the cameras needs device
access they don't have.

## Python version

[`python/sipl_player.py`](python/sipl_player.py) is the same player, written
with the module's [SIPL Python bindings](../../operators/sipl_capture_op/python/README.md). It needs a
Holoscan SDK installed with its Python packages, including Vision and
Visualization, and CuPy. It takes the C++ player's options except
`--separate`: its windows would need a shared serialization domain, which a
Python graph cannot declare for `HolovizOp`. Two other differences:

- `--raw` unpacks RAW10 with the package's `Raw10UnpackOp`, a CuPy kernel.
- `--frame-limit N` stops after N frames from the first camera.

```bash
./holoscan_camera run sipl_player --language python --run-args \
  '--json-config applications/config/sipl/vb1940_dual.json'
```

Its `validate` mode runs `--validate`, which needs no camera:

```bash
./holoscan_camera run sipl_player validate --language python
```

## Tests

`--validate` compiles the graph and opens no camera. CTest runs it for the
ISP and RAW graphs, tiled and `--separate`, with windows and `--headless`
(labels `plan` and `gpu`: the plans bind CUDA-device outputs, so they need a
visible GPU).

With the SIPL Python bindings, CTest also runs the Python version's
`--validate` for the ISP and RAW graphs, with a window and `--headless`
(`python-camera.sipl-player-validate-*`). `python-camera.sipl-player` runs its
tiled graph headless with two fake cameras: the second tile must show the
second camera's frame from before the first camera's, and a second camera that
stops must not stop the window. These tests need the SDK's Vision and
Visualization Python packages, CuPy and a GPU; configure skips them without
the packages or CuPy.

## Migration Notes

This application is a Holoscan SDK 5 port of Holoscan Sensor Bridge's
`examples/sipl_player.cpp`, and its Python version of `examples/sipl_player.py`.
Differences from those versions:

- `--raw`: the Holoscan Sensor Bridge version also ran its `ImageProcessorOp`
  (optical black and white balance) on this path. This module does not depend
  on Holoscan Sensor Bridge, so the colors are uncorrected.
- `--separate`: the Holoscan Sensor Bridge version ran each camera as a
  separate application. Here all windows belong to one graph, as described
  above.
