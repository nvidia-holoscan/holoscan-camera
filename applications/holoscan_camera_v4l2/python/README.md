# V4L2 Python application

[`v4l2_capture.py`](v4l2_capture.py) builds a Holoscan SDK 5 graph using the
native `V4l2CaptureOp`. It can validate the graph, capture frames, or display a
live Holoviz preview. Its CLI modes are registered in [`metadata.json`](metadata.json).
For the C++ application, see the [parent guide](../README.md).

## Setup

Use a matching SDK 5 environment with Camera Python bindings. The
[Camera Python guide](../../../python/README.md) describes dependencies,
package imports, SDK source builds, and builds against an installed SDK.
See the [V4L2 binding interface](../../../python/README.md#v4l2) for constructor
arguments and the [native operator guide](../../../operators/v4l2_capture_op/README.md)
for capture and memory-placement contracts.

Run every command below from the Camera repository root. Live capture requires
a Linux V4L2 camera with a supported YUYV mode and access to its device node.
Preview additionally requires the [Visualization and display setup](#live-preview).

## Run the sample

The Camera CLI registers both the operator and sample for Python. After
completing the setup above, run these commands from the repository root:

| Mode | Behavior | Camera / display required |
| --- | --- | --- |
| `validate` (default) | Compile the Python graph and check its contracts | Neither |
| `capture` | Receive 120 frames by default and print frame information | Camera |
| `preview` | Show live captured frames until the window closes | Camera and display |

Capture and preview use the same native V4L2 operator. Preview adds a layout
adapter and the SDK's `HolovizOp`; neither mode saves images or video.

```bash
./holoscan_camera run holoscan_camera_v4l2 validate --language python --local
./holoscan_camera run holoscan_camera_v4l2 capture --language python --local \
  --run-args='--device /dev/video0 --width 640 --height 480 --fps 30 --frames 120 --timeout 10'
```

The CLI builds the native operator and Python bindings, and adds the build's
Python package directory to `PYTHONPATH`. `--language python` skips the C++ sample
executable. The CLI prefers Python when no language is specified; use
`--language cpp` for the native sample and SDK installations without Python bindings.
`--local` uses the current machine or development container; omitting
it uses the CLI's Docker workflow, whose SDK image must also include Python support.
The Python interpreter must match the SDK environment. Set `HOLOSCAN_SDK_INSTALL_DIR`
to its SDK installation if it is not found automatically.

If needed, explicitly select the interpreter from that environment:

```bash
export HOLOSCAN_CLI_PYTHON_BIN="$(command -v python3.12)"
python3.12 -c 'import holoscan'
```

The sample launcher uses this exact executable, even if `python3` in the same
directory names a different Python version.

If the import fails, finish installing or exposing the SDK Python package before
running the sample. `--local` does not enter a container or install the SDK.

When switching between host and Docker builds, use a separate build directory
for local build/run commands to avoid reusing a cache with different source paths:

```bash
export HOLOSCAN_CLI_BUILD_PARENT_DIR="$PWD/build-local-python"
```

This also resolves a CMake cache referring to `/workspace/holoscan_camera` when
the local checkout has a different path. The CLI test driver uses its own
`build/ctest-v4l2_capture_op` directory.

To run the script directly after the
[CMake build](../../../python/README.md#build-against-an-installed-sdk),
use its package directory with the matching Core package importable:

```bash
export PYTHONPATH="$PWD/build-camera-python/python/lib${PYTHONPATH:+:$PYTHONPATH}"
python3.12 applications/holoscan_camera_v4l2/python/v4l2_capture.py --validate
python3.12 applications/holoscan_camera_v4l2/python/v4l2_capture.py --device /dev/video0 --width 640 --height 480 --fps 30 --frames 120
```

Choose a YUYV mode supported by the camera. Graph validation checks contracts
without opening the device; capture opens it during the native lifecycle.
The sample defaults to host memory and finishes after its Python consumer receives
the requested number of images. `--timeout` bounds the run (10 seconds by default),
including when the camera opens but produces no frames. Timeout or Ctrl-C stops and
joins the capture session before returning.

Use `--frame-id NAME` to set the image coordinate frame (default:
`camera_optical_frame`). `--memory-kind pinned` selects pinned host memory;
`--memory-kind device --cuda-device 0` selects GPU memory and explicitly binds the
camera's output to that device. The counter reads image metadata without copying
GPU pixels to the CPU. Live GPU capture requires a usable CUDA device.

## Live preview

Preview requires matching Holoscan SDK 5 Visualization Python bindings, NumPy,
and a compatible NVIDIA GPU with display access. Use an SDK development image
that includes Visualization, or build the SDK with
`HOLOSCAN_BUILD_VISUALIZATION=ON` and Python enabled. Verify the environment:

```bash
python3.12 -c 'from holoscan_visualization.operators import HolovizOp'
python3.12 -m pip install numpy
```

Run the CLI preview mode:

```bash
./holoscan_camera run holoscan_camera_v4l2 preview --language python --local \
  --run-args='--device /dev/video0 --width 640 --height 480 --fps 30'
```

Close the **Holoscan V4L2 preview** window or press **Escape** to stop capture.
This mode uses `--preview --frames 0 --timeout 0` to run until the window closes.
Zero disables the deadline only for continuous preview. Add
`--frames 120 --timeout 10` inside `--run-args` to limit capture, or use `--preview` with the standalone Python
sample. `--validate --preview` checks the graph without opening a camera or window.

The preview path is `V4l2CaptureOp -> YuyvPreviewOp -> HolovizOp`. The layout
adapter changes Camera's `[height, 2 * width]` byte rows into the
`[height, width, 2]` layout required by the pinned Holoviz YUYV input. It copies
pixels into a host output pool and forwards image and sample metadata. The native
camera output remains unchanged. Both preview edges use SDK queues with depth one
and `DROP_OLDEST`; Holoviz runs in its own partition. The sample no longer needs
an FFplay subprocess, a Python preview queue, or pipe-writing logic.

The separate `FrameCounterOp` logs frames received by Python and implements
`--frames`. In preview mode its camera edge also uses a depth-one `DROP_OLDEST`
queue so it cannot backpressure capture during display startup or consumer lag.
This count does not measure camera exposures or frames displayed by Holoviz. Rendering
and the layout copies add overhead, so preview is for visual inspection.
Capture without `--preview` does not import NumPy or Visualization.
The adapter supports host and pinned memory; GPU-memory preview is rejected
because its NumPy view requires host-accessible pixels.

YUV conversion defaults to BT.601 with limited range. Use
`--yuv-model bt709` or `bt2020` and `--yuv-range full` to match your camera's
colorimetry. These settings affect display conversion, not camera capture.
Holoviz processes window events on arriving frames. If capture stalls during an
unbounded preview, use Ctrl-C; a finite `--timeout` also stops the session.

The process needs access to your graphical display. When using Docker, forward
the X11 socket, `DISPLAY`, and the display authorization file; the CLI Docker
workflow provides display options. `--local` inside a container uses that
container's existing display access.

## Tests without a camera

To build or test the operator through the CLI:

```bash
./holoscan_camera build v4l2_capture_op --language python --local
./holoscan_camera test v4l2_capture_op --language python --local --no-xvfb
```

These tests do not open a camera. See [Live capture tests](#live-capture-tests)
for checks that require a physical camera.

Sample tests check deadlines and cleanup using synthetic SDK graphs, preview
layout conversion with pixel and metadata preservation, and the CLI's exact
interpreter selection. When Visualization is installed, they also compile the
preview graph without opening a camera or display. Install
`python/requirements-test.txt` to run the sample tests.
Live capture remains a separate hardware qualification step.

## Live capture tests

To validate live tensor delivery and camera release, use a camera supporting
640x480 YUYV at 30 FPS. With the built packages on `PYTHONPATH`, run:

```bash
python3.12 -m pip install numpy pytest
HOLOSCAN_CAMERA_TEST_DEVICE=/dev/video0 python3.12 -m pytest -q python/tests/test_v4l2_hardware.py
```

The test captures 60 frames twice in the same process. It checks image dimensions,
encoding, coordinate frame, increasing device sequences, NumPy/DLPack access to
the uint8 tensor, and successful completion. Without
`HOLOSCAN_CAMERA_TEST_DEVICE`, it is skipped and never opens a camera.
