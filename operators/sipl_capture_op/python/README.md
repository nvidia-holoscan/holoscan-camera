# SIPL Python bindings

`holoscan_camera.operators.SIPLCaptureOp` adds the native SIPL operator to a
Holoscan SDK 5 Python graph, in the same provider as V4L2 and Argus. NvSIPL capture,
the service's buffers, readiness notifications, and lifecycle cleanup remain in
C++. A `holoscan_camera.SIPLCaptureService` owns one NvSIPL camera configuration;
the `SIPLCaptureOp` of each of its cameras receives it as the `service`
constructor handle.

The ARM64 wheel targets Jetson AGX Thor with JetPack 7.2.1 (R39.2), SIPL API v2,
the matching NvSIPL runtime, and an SDK 5 Python installation. R38 SIPL is
unsupported by the wheel; the native operator retains its separate, experimental
R38 C++ source-build path. Python capture and native C++ capture are qualified
separately.

## Build

Use a Holoscan SDK 5 revision with the [required Python typing tools](../../../python/README.md#build-with-the-sdk),
shared libraries, and Python enabled. The SIPL operator also needs an SDK with
constructor handles. The selected Python 3.12+ interpreter must import the
matching SDK 5 `holoscan` package.

On a Jetson or IGX system with the native build dependencies, run from the Camera
repository root:

```bash
python3.12 -m pip install -r python/requirements-test.txt
cmake -S . -B build-sipl-python -G Ninja \
  -Dholoscan_ROOT="$HOLOSCAN_SDK_INSTALL_DIR" \
  -DPython3_EXECUTABLE="$(command -v python3.12)" \
  -DHOLOSCAN_CAMERA_BUILD_ALL=OFF \
  -DHOLOSCAN_CAMERA_BUILD_PYTHON=ON \
  -DOP_sipl_capture_op=ON \
  -DHOLOSCAN_BUILD_PYTHON_STUBS=ON \
  -DHOLOSCAN_CAMERA_BUILD_TESTING=ON
cmake --build build-sipl-python -j4
ctest --test-dir build-sipl-python -R '^python-camera\.' --output-on-failure --no-tests=error
```

`HOLOSCAN_CAMERA_BUILD_PYTHON` enables the shared Camera provider, and
`OP_sipl_capture_op=ON` selects the native SIPL operator: with Python enabled, its
bindings and metadata schema are included automatically. Selecting the SIPL
operator or the `sipl_capture` application with the Camera CLI's
`--language python` enables both. Add `OP_argus_capture_op=ON` or
`OP_v4l2_capture_op=ON` to include Argus (see [Argus Python bindings](../../argus_capture_op/python/README.md))
or V4L2 as well; a provider that includes Argus registers its Python tests only
with `HOLOSCAN_CAMERA_RUN_ARGUS_TESTS=ON`.

Importing Camera does not load NvSIPL. Requesting `SIPLCaptureOp` or
`SIPLCaptureService` imports `_sipl`, which loads the BSP libraries through normal
ELF dependencies. Runtime tests and explicit R39 stub checks need that runtime;
normal header-only wheel builds stage the committed optional-backend stubs. `python-camera.sipl` covers the operator, the service handle, the
[sipl_capture](../../../applications/sipl_capture/README.md) application, and metadata
conversion; `python-camera.sipl-converters` runs the CuPy converters on synthetic
frames and needs a GPU. The converters need CuPy, which the provider does not
depend on; without an importable CuPy, configure skips that test. The native
`sipl_operator_catalog_test` covers the same registry row from C++.

The generated operator stub types `service` as `holoscan_camera.SIPLCaptureService`
through the SDK's `HANDLE_ANNOTATIONS`. Its committed reference,
`operators/sipl_capture_op/python/sipl_capture_op.pyi`, declares
`SIPLCaptureOp`. On a matching R39 runtime, build
`holoscan-camera-check-sipl-stubs` to generate and validate the optional registry
declarations. The private service stub is checked with
`python -m mypy.stubtest holoscan_camera._sipl` on that runtime.

## Capture and validate

The [sipl_capture](../../../applications/sipl_capture/README.md) application captures
from every camera of a configuration and logs its frames and their metadata;
with `--validate`, it compiles its graph without opening a camera. For a viewer
with HoloViz, see the Python version of
[sipl_player](../../../applications/sipl_player/README.md#python-version).

Its frames stay on the GPU, the operator's default. Device output needs
an explicit GPU binding before compiling:

```python
import holoscan as hs
from holoscan_camera import SIPLCaptureService
from holoscan_camera.operators import SIPLCaptureOp

service = SIPLCaptureService(json_config="applications/config/sipl/vb1940_dual.json")
graph = hs.Graph("sipl-device", default_clock=hs.RealtimeClock)
camera = graph.op(SIPLCaptureOp, "camera", service=service, camera_index=0)
options = hs.CompileOptions()
options.deployment.bind_tensor_output_device(
    operator_path="camera", output_port="frame", device=hs.execution.DeviceId(0)
)
```

## Configuration and metadata

| Argument | Default | Meaning |
| --- | --- | --- |
| `service` | required | The `SIPLCaptureService` of the camera's configuration, shared by its cameras' operators |
| `camera_index` | required | Zero-based index of the camera in the configuration |
| `memory_kind` | `"device"` | `"device"`, `"pinned"`, or `"host"`; device output needs an explicit GPU binding |

Both `graph.op(SIPLCaptureOp, "camera", **arguments)` and
`SIPLCaptureOp(graph, "camera", **arguments)` use the SDK's registered proxy.
`camera_index` and `memory_kind` are immutable and replayed when the SDK clones
the graph. The operator holds the service's C++ object, not its Python wrapper,
and a construction that fails holds nothing and leaves the graph unchanged.

`SIPLCaptureService(camera_config="", json_config="", raw_output=False,
capture_queue_depth=4, nito_base_path="/var/nvidia/nvcam/settings/sipl",
timeout_us=3000000, cuda_device=0)` takes the native constructor's arguments.
Constructing it opens no camera. `get_camera_info()` and `camera_count()`
initialize NvSIPL, which opens the cameras; `list_available_configs()` prints the
configurations. `CameraInfo`, `PixelFormat`, and `BayerFormat` describe each
camera's frames, including the RAW geometry and Bayer phase.

The `sensor_data` port uses `holoscan_camera.schema.SIPLFrameMetadata` and the
canonical payload name `holoscan.camera.SIPLFrameMetadata`; `SIPLWbGain`
is exported from the same schema package. The SDK generates the dataclass, its
typing stub, and the native conversion adapter from `sipl_frame_metadata.fbs`.
Each record carries the ISP statistics, about 400 KB. A consumer that only
counts records can read them with `selected_sample()`, which converts a record
to Python only when its data is read, as sipl_capture's metadata printer does.

`holoscan_camera.operators.converters` provides CuPy operators for the frame formats
`SIPLCaptureOp` publishes: `Nv12ToRgbOp` converts the ISP's NV12 (BT.709, full
range) to RGB8, and `Raw10UnpackOp` unpacks RAW10 into the 16-bit Bayer images
that the SDK's `BayerDemosaicOp` takes. Both take frames in CUDA device memory,
`SIPLCaptureOp`'s default `memory_kind`; a frame in host or pinned memory fails
the run with an error that says so. Neither `import holoscan_camera` nor
`import holoscan_camera.operators` imports it, as it needs CuPy (for example
`cupy-cuda13x`).

## Installation and qualification

The SIPL files install with the rest of the provider, in component
`holoscan-camera-python_libs`; the native operator remains in `holoscan-camera`.
A Camera wheel built with SIPL also contains the native SIPL library and the
metadata codec; NvSIPL and the Jetson BSP runtime libraries must be provided by the
system. See [Build a Camera wheel](../../../python/README.md#build-a-camera-wheel).

Before qualifying Python capture, run the sample with a SIPL camera, check frame
and metadata output, and repeat it to verify session cleanup and camera reuse.
