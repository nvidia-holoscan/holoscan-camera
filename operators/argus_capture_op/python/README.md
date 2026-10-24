# Argus Python bindings

`holoscan_camera.operators.ArgusCaptureOp` adds the existing native Argus operator
to a Holoscan SDK 5 Python graph. Capture sessions, bounded native buffers,
readiness notifications, lifecycle cleanup, and copies into SDK tensor pools
remain in C++. The provider uses the SDK authoring registry and a nanobind
stable-ABI initializer, following the SDK's Vision module.

This provider builds for ARM64 and targets Jetson AGX Orin with a compatible
BSP, CUDA, Holoscan SDK 5 Python installation, and Argus-compatible camera. See the
[native operator guide](../README.md) for dependencies.
Python capture and native C++ capture are qualified separately.

## Build

Use a Holoscan SDK 5 revision with the [required Python typing tools](../../../python/README.md#build-with-the-sdk),
shared libraries, and Python enabled. Native SDK headers and libraries alone
are insufficient: the selected Python 3.12+ interpreter must also import the
matching SDK 5 `holoscan` package.


On a Jetson with the native build dependencies installed, run from the Camera
repository root:

```bash
python3.12 -m pip install -r python/requirements-test.txt
cmake -S . -B build-argus-python -G Ninja \
  -Dholoscan_ROOT="$HOLOSCAN_SDK_INSTALL_DIR" \
  -DPython3_EXECUTABLE="$(command -v python3.12)" \
  -DHOLOSCAN_CAMERA_BUILD_ALL=OFF \
  -DHOLOSCAN_CAMERA_BUILD_PYTHON=ON \
  -DOP_argus_capture_op=ON \
  -DHOLOSCAN_BUILD_PYTHON_STUBS=ON \
  -DHOLOSCAN_CAMERA_BUILD_TESTING=ON \
  -DHOLOSCAN_CAMERA_RUN_ARGUS_TESTS=ON
cmake --build build-argus-python -j4
ctest --test-dir build-argus-python -R '^python-camera\.' --output-on-failure --no-tests=error
```

`HOLOSCAN_CAMERA_BUILD_PYTHON` enables the shared Camera provider.
Select V4L2 separately with `OP_v4l2_capture_op=ON` when both backends are needed.
`OP_argus_capture_op=ON` selects the native Argus operator. With Python enabled,
its bindings and metadata schema are included automatically. With
`HOLOSCAN_CAMERA_BUILD_ALL=OFF`, Argus remains disabled unless selected directly
or required by an application or package. V4L2-only Python builds on generic
ARM64 do not require Jetson libraries. Explicitly enabling Argus on a non-ARM64
target is an error. When switching an existing build to V4L2 only, disable
`OP_argus_capture_op` and any application or package that requires it.
Selecting the Argus app or operator with the Camera CLI's `--language python`
enables the shared Python build flag and the required native operator.
Native unit tests also require GoogleTest when testing is enabled.

The Python tests do not open a camera, but importing the native extension still
requires the matching Jetson runtime libraries. For an ARM64 builder without
that runtime, set both `HOLOSCAN_CAMERA_RUN_ARGUS_TESTS=OFF` and
`HOLOSCAN_BUILD_PYTHON_STUBS=OFF`: native compilation remains enabled, while
runtime tests and import-based stub generation are disabled. Such a build is
not runtime qualification.

To build nested in the SDK, enable `HOLOSCAN_BUILD_CAMERA`,
`HOLOSCAN_BUILD_PYTHON`, `HOLOSCAN_CAMERA_BUILD_PYTHON`, and
`OP_argus_capture_op`, and select this Camera
revision using `HOLOSCAN_CAMERA_GIT_REPOSITORY`/`HOLOSCAN_CAMERA_GIT_TAG` or
`CPM_holoscan_camera_SOURCE`. Run the SDK's `run` script from its source directory.
Source overrides must be visible in its container.
Camera reuses the SDK's nanobind selection and shared Python staging root and
adds its extension, metadata codec, and typing generation to `holoscan-python`.

V4L2 uses the SDK's import-based stub generator during normal builds. Optional
backend stubs are staged from checked-in declarations so the header-only builder
never imports Argus or SIPL. On a matching R39 runtime, explicitly build
`holoscan-camera-check-argus-stubs` to generate the optional registry declarations
and check them against the committed references. Generate refreshed declarations
from `argus_operators.pyi` with `python/split_operator_stubs.py` after an intentional
constructor change.

`HOLOSCAN_CAMERA_BUILD_TESTING=ON` with `HOLOSCAN_BUILD_PYTHON_STUBS=ON` enables
positive and negative consumer checks for each selected operator and requires
100% public type completeness using the
SDK checker. Argus tests also include `mypy.stubtest` and metadata round trips.

## Capture and validate

On a compatible Jetson with the matching SDK Python package importable, the
Camera CLI builds the provider and launches
[`applications/holoscan_camera_argus/python/argus_capture.py`](../../../applications/holoscan_camera_argus/python/argus_capture.py):

```bash
./holoscan_camera modes holoscan_camera_argus --language python
./holoscan_camera run holoscan_camera_argus validate --language python --local
./holoscan_camera run holoscan_camera_argus capture --language python --local \
  --no-local-build --run-args='--camera 0 --mode 0 --frames 300'
```

Use the same Python 3.12+ environment for the CLI, SDK, and sample. Point
`HOLOSCAN_SDK_INSTALL_DIR` at the SDK installation when it is not auto-detected.
Graph validation does not open a camera; capture requires a running
`nvargus-daemon`. Pass `--language cpp` to select the native sample explicitly;
the CLI prefers Python when both languages are available.

From the Camera repository root, with the matching SDK Python package importable:

```bash
export PYTHONPATH="$PWD/build-argus-python/python/lib${PYTHONPATH:+:$PYTHONPATH}"
python3.12 applications/holoscan_camera_argus/python/argus_capture.py --validate
sudo systemctl start nvargus-daemon
python3.12 applications/holoscan_camera_argus/python/argus_capture.py \
  --camera 0 --mode 0 --width 1920 --height 1080 --fps 30 --format nv12 --frames 300
```

Choose a camera, sensor mode, output dimensions, and frame rate supported by
libargus. Camera indices are Argus enumeration indices, not `/dev/videoN` indices.
`--validate` compiles both Python consumers without opening a camera. Live capture
prints frame and metadata information and requests completion after receiving
`--frames` metadata messages. The two outputs are published independently; the
metadata limit does not guarantee the image consumer received the same count.
The sample's `--run-timeout` defaults to 30 seconds, and its asynchronous session
context stops and joins native capture on timeout or a Python exception.

The sample selects host memory. The operator's native default remains device
memory. `frame` carries `holoscan.schema.Image` with one rank-1 `uint8` tensor of
`width * height * 3 / 2` bytes, containing contiguous NV12 or I420 planes.
A Python consumer declares an `Image` input with `spec.input(...)` and accesses
the embedded tensor through `image.data`. Queue depth is configured on
`graph.add_flow(..., queue_depth=2)`, as in the sample.
The SDK Tensor API supplies DLPack access; this binding adds no pixel conversion.

For device output, bind the GPU before compiling:

```python
import holoscan as hs
from holoscan_camera.operators import ArgusCaptureOp

graph = hs.Graph("argus-device", default_clock=hs.RealtimeClock)
camera = graph.op(ArgusCaptureOp, "camera", memory_kind="device")
options = hs.CompileOptions()
options.deployment.bind_tensor_output_device(
    operator_path="camera", output_port="frame", device=hs.execution.DeviceId(0)
)
plan = hs.compile(graph, options)
assert plan.ok, plan.json()
```

## Configuration and metadata

All native constructor fields are available as keyword arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `camera_index`, `sensor_mode` | `0`, `0` | Argus camera and mode indices |
| `width`, `height`, `fps` | `1920`, `1080`, `30.0` | Even output dimensions and requested rate |
| `pixel_format` | `"nv12"` | `"nv12"` or `"i420"` |
| `buffer_count` | `6` | Native buffer count, from 3 to 64 |
| `drop_policy` | `"drop_oldest"` | `"drop_oldest"` or `"drop_newest"` |
| `timeout_ms` | `2000` | No-frame deadline; must cover at least one frame period |
| `cuda_device` | `0` | Jetson integrated GPU; only zero is supported |
| `frame_id` | `"camera_optical_frame"` | Image coordinate frame name |
| `memory_kind` | `"device"` | `"device"`, `"host"`, or `"pinned"` |
| `integration_start_offset_ns` | `None` | Optional calibrated offset from VI SOF to integration start |

Both `graph.op(ArgusCaptureOp, "camera", **parameters)` and
`ArgusCaptureOp(graph, "camera", **parameters)` use the SDK's registered proxy.
Configuration is immutable and replayed when the SDK clones operator factories
during graph embedding and compilation. This is
the SDK's constructor-replay path for an operator with native constructor
configuration; it does not expose mutable `Params` or `set_params`. The
native constructor still validates geometry and constraints between fields.
Only set `integration_start_offset_ns` when sensor calibration establishes it;
VI SOF is not automatically an integration-start timestamp.

The `metadata` port uses `holoscan_camera.schema.ArgusFrameMetadata` and the
canonical payload name `holoscan.camera.ArgusFrameMetadata`.
`ArgusTimestampClock` is exported from the same Python schema package.
The SDK generates the dataclass, its typing stub, and native conversion adapter
from `argus_frame_metadata.fbs`. Python can read sequence numbers, raw sensor and
SOF timestamps, exposure, gains, AE/AWB state, drop counters, and capture-time
validity without maintaining a second schema definition.

## Installation and qualification

The extension, generated metadata adapter, and Python files install under
`lib/python<version>/site-packages/holoscan_camera`, in component
`holoscan-camera-python_libs`; the native operator remains in `holoscan-camera`.
Typing-enabled builds install facade stubs, the generated metadata/private-module
stubs, and `py.typed`. `HOLOSCAN_BUILD_PYTHON_STUBS=OFF` omits installed typing files.
Build and install trees also include provider distribution metadata so the SDK's
module loader exposes `holoscan.camera` as the same package as `holoscan_camera`.
Both import orders preserve operator and metadata codec identities. Importing
Core alone does not load the Camera catalog.

The [Argus binding tests](tests/) check import order, constructor validation, optional timing
correction, both output payloads, Python consumers, GPU placement, Python/C++
plan equality, and metadata conversion through the runtime without capture.
Before qualifying Python capture, run the sample on Jetson AGX Orin, check frame
and metadata output, and repeat it to verify session cleanup and camera reuse.

## Build a Camera wheel with Argus

Follow the shared [Camera wheel instructions](../../../python/README.md#build-a-camera-wheel).
ARM64 wheel builds include V4L2, SIPL v2, and Argus using R39 development headers.
Argus runs on supported R39 Orin hardware with its matching CUDA, EGL, and BSP
libraries. These runtime libraries are not bundled in the wheel.

Argus has its own `_argus` extension. Importing Camera or V4L2 does not load it;
requesting `ArgusCaptureOp` does. Unsupported systems may reject that specific
import while V4L2 remains usable. The `linux_aarch64` tag describes architecture,
not backend hardware support. Qualify live capture and camera reuse on the target
Orin independently of camera-free graph tests.
