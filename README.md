# Holoscan Camera

Camera source components for Holoscan SDK 5.x.

This is a Holoscan Module: a self-contained, redistributable C++ library that
extends [Holoscan SDK](https://developer.nvidia.com/holoscan-sdk) with reusable
operators under the `holoscan::camera` namespace.

Choose the backend that matches your camera and host, then use its reference
application to validate the graph and capture frames.

## Supported platforms

Camera requires an SDK installation with `holoscan::sensor_io` and CUDA 13.
Backend support also depends on the host BSP, camera driver, and development
libraries; installing the SDK alone does not establish camera compatibility.

| Operator | Ubuntu 24.04 | DGX OS | IGX Thor + IGX OS 2.0 | Jetson Orin + JetPack 7.2.1 | Jetson AGX Thor + JetPack 7.2.1 |
| --- | --- | --- | --- | --- | --- |
| `V4l2CaptureOp` | Supported | Supported | Supported | Supported | Supported |
| `SIPLCaptureOp` | - | - | - | - | Supported |
| `ArgusCaptureOp` | - | - | - | Supported | - |

The table describes Holoscan Camera 1.0 support. "Supported" identifies a
combination intended for Holoscan validation. SIPL capture is supported only on
Jetson AGX Thor with JetPack 7.2.1 in this release.
SIPL on IGX Thor T5000 requires JetPack 7.2.1.
V4L2 capture is supported on both IGX Thor T5000 and T7000 with IGX OS 2.0.
See the [known issues](RELEASE_NOTES.md#known-issues) for current build and
capture limitations on these platforms.

IGX OS 2.0 corresponds to R38.5; JetPack 7.2.1 corresponds to R39.2.
On IGX R38.5, the container skips Argus and SIPL dependency downloads.
Experimental SIPL source builds on IGX Thor T5000 require the matching R38.5
SIPL development archive under `/usr/src/jetson_sipl_api`. The
`./holoscan_camera` wrapper detects that host tree and mounts it read-only into
the build container; it does not download or substitute R39 headers. See the
[SIPL operator guide](operators/sipl_capture_op/README.md#igx-r385-host-prerequisite)
for the required pre-step and an alternate source-path override. Installing
these headers does not establish capture compatibility or release support.
SIPL targets default off on R38.5 and must be enabled explicitly. For a V4L2-only
build, use
`-DHOLOSCAN_CAMERA_BUILD_ALL=OFF -DAPP_holoscan_camera_v4l2=ON`. See the
[Argus build guide](operators/argus_capture_op/README.md) for an explicit host
header mount for experimental builds. IGX Argus capture is not a supported
combination in the table above.

### Python wheel support

One native wheel is built per architecture. The ARM64 wheel contains V4L2,
R39 SIPL API v2, and Argus in separate native extensions. V4L2 works without
loading the optional BSP backends on SBSA, DGX Spark, and R38.
SIPL is supported only on Jetson AGX Thor with JetPack 7.2.1 (R39.2).
Argus is supported only on Jetson Orin with JetPack 7.2.1 (R39.2).
Both require the matching BSP runtime.
The x86_64 wheel provides native V4L2 support; SIPL and Argus require ARM64.
See the [Python guide](python/README.md#included-operators) for import and build details.

## Operators

<!-- markdownlint-disable-next-line MD033 -->
<a id="operators-and-documentation"></a>

| Operator | Purpose | Documentation |
| --- | --- | --- |
| `V4l2CaptureOp` | Capture packed YUYV frames from Linux V4L2 devices into host, pinned-host, or CUDA device memory | [Usage and interface](operators/v4l2_capture_op/README.md) |
| `SIPLCaptureOp` | Capture RAW10/NV12 frames from NvSIPL-managed cameras on Jetson AGX Thor (aarch64 only) | [Usage and interface](operators/sipl_capture_op/README.md) |
| `ArgusCaptureOp` | Capture ISP-processed Jetson Argus images with sensor metadata and bounded native buffers | [Usage, timing contract, and qualification limits](operators/argus_capture_op/README.md) |

## Applications

| Application | Purpose | Guide |
| --- | --- | --- |
| `holoscan_camera_v4l2` | Validate a graph or stream V4L2 frames | [V4L2 application](applications/holoscan_camera_v4l2/README.md) |
| `holoscan_camera_argus` | Receive Jetson Argus frames and metadata | [Argus application](applications/holoscan_camera_argus/README.md) |
| `sipl_frame_saver` | Save camera frames and metadata to disk | [SIPL frame saver](applications/sipl_frame_saver/README.md) |
| `sipl_stereo_monitor` | Monitor a stereo rig and cross-camera timing | [SIPL stereo monitor](applications/sipl_stereo_monitor/README.md) |

## Configuration

Configure Camera operators when constructing the C++ graph:

| Backend | Operator configuration | Reference application configuration |
| --- | --- | --- |
| V4L2 | Constructor arguments for device, dimensions, frame rate, coordinate frame, and memory placement | CLI options such as `--device` and `--memory-kind` |
| SIPL | A shared `SIPLCaptureService` plus per-camera operator arguments | CLI options and vendor JSON platform files selected with `--json-config` |
| Argus | An `ArgusCaptureConfig` value | CLI options for camera/mode selection, image size, and memory placement |

### YAML support

Camera currently provides no `from_yaml` or `from_yaml_node` loader. Applications
that use YAML must parse their own settings and pass the resulting values to the
C++ constructors. The SIPL [vendor JSON configurations](applications/config/sipl/README.md)
describe the NvSIPL platform; they are consumed by that stack and do not provide
a general Camera operator configuration format.

Use the operator guides for C++ construction examples and each application's
guide for the CLI options it implements.

## Build, test, and consume

Set `HOLOSCAN_SDK_ROOT` to an SDK 5.x installation containing `holoscan::sensor_io`;
see [SDK setup](#holoscan-sdk-50-setup) below. Run these commands from the Camera
repository root. Graph validation and unit tests do not qualify physical capture;
follow each application guide for live-camera tests.

### Quick Start

The wrapper installs the CLI from [`requirements-cli.txt`](requirements-cli.txt)
and requires Python 3.11 or newer. If `python3` is older, as on Ubuntu 22.04,
run the wrapper from an activated Python 3.11+ virtual environment.

Run these commands from the repository root after completing SDK setup:

```bash
# Build and validate the C++ V4L2 example graph without a camera.
./holoscan_camera run holoscan_camera_v4l2 --language cpp

# Run the reference application's tests.
./holoscan_camera test holoscan_camera_v4l2 --language cpp

# Build the Debian package and the raw CPack TGZ.
./holoscan_camera package holoscan-camera --pkg-generator DEB,TGZ
```

For device access, capture options, C++ integration, and frame placement, see the
[V4L2 operator guide](operators/v4l2_capture_op/README.md).

The V4L2 sample also provides Python `validate`, `capture`, and `preview` modes.
The CLI prefers Python when `--language` is omitted. Use `--language cpp` for
the native sample, including with an SDK installation without Python bindings.
With matching SDK and Visualization Python bindings, NumPy, and a compatible
NVIDIA GPU with display access, show live camera frames with:

```bash
./holoscan_camera run holoscan_camera_v4l2 preview --language python \
  --run-args='--device /dev/video0 --width 640 --height 480 --fps 30'
```

Close the preview window or press **Escape** to stop. See the
[Python application guide](applications/holoscan_camera_v4l2/python/README.md)
for environment setup, supported camera modes, and tests.

`SIPLCaptureOp` targets Jetson AGX Thor (aarch64) and needs a mapped NvSIPL-managed
camera; see [sipl_player](applications/sipl_player),
[sipl_frame_saver](applications/sipl_frame_saver) and
[sipl_stereo_monitor](applications/sipl_stereo_monitor) for reference
applications, and the [SIPL operator guide](operators/sipl_capture_op/README.md)
for supported JetPack/L4T versions and usage. `sipl_player` also has a
Python version.

### Building Without HoloHub CLI

| Requirement | Version |
| --- | --- |
| Holoscan SDK | 5.0 with `sensor_io`; see [SDK setup](#holoscan-sdk-50-setup) |
| CUDA Toolkit | 13.x |
| CMake | >= 4.0 |
| C++ compiler | C++20 |

Start with V4L2 and its reference application; this avoids requiring SIPL or
Argus development libraries on a V4L2-only host.

```bash
cmake -S . -B build -G Ninja \
    -Dholoscan_ROOT="$HOLOSCAN_SDK_ROOT" \
    -DAPP_holoscan_camera_v4l2=ON \
    -DHOLOSCAN_CAMERA_BUILD_TESTING=ON
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure -LE gpu
```

`-LE gpu` drops the device-resident placement check, which is the one test that
needs a visible CUDA device. Drop the exclusion on a runner that has one.

For SIPL or Argus, follow the operator-specific prerequisites before enabling
those targets. `HOLOSCAN_CAMERA_BUILD_ALL=ON` enables additional components
whose development dependencies may be absent on your host.

### Consume the installed module

The package installs `holoscan-camera-config.cmake` under
`<libdir>/cmake/holoscan-camera` and its exported targets under
`<libdir>/cmake/holoscan`. After installing Camera and its SDK dependencies,
a CMake consumer uses the Camera package and its exported targets:

```cmake
find_package(holoscan-camera CONFIG REQUIRED)
target_link_libraries(my_pipeline PRIVATE holoscan::camera)
```

Add the installation prefixes to `CMAKE_PREFIX_PATH` when they are outside CMake's
search paths. `holoscan::camera` aggregates the operators enabled in that build;
consumers may instead link `holoscan::v4l2_capture_op`,
`holoscan::sipl_capture_op`, or `holoscan::argus_capture_op` when available.

## Benchmarks

Read the [V4L2 benchmarks](operators/v4l2_capture_op/benchmarks.md) and
[SIPL benchmarks](operators/sipl_capture_op/benchmarks.md) for the tested hardware,
commands, and observed capture behavior. Use the
[Argus operator's qualification results](operators/argus_capture_op/README.md#platform-and-dependencies)
for its current capture evidence.

Optional [Python bindings](python/README.md) expose native capture operators
to Holoscan SDK Python graphs. See individual components for support details.

## Holoscan SDK 5.0 Setup

Choose a Holoscan SDK 5.0 source baseline for your development.

<!-- module-docs:sdk-source -->
The published SDK 5.0.0 EA3 source tag (`v5.0.0-ea3`) is one baseline; see the
[SDK 5.0.0 EA3 release notes](https://github.com/nvidia-holoscan/holoscan-sdk/blob/v5.0.0-ea3/RELEASE_NOTES.md)
for release details.
<!-- /module-docs:sdk-source -->

For custom SDK development, use the installation built from your selected SDK checkout.

For SDK container selection, see the
[developer guide](DEVELOPER.md#public-sdk-container).

### Using Holoscan SDK built from source

Set `HOLOSCAN_SDK_ROOT` explicitly to the resulting SDK installation
directory. The installation must include `holoscan::sensor_io`, which this
module requires. See [SDK installation troubleshooting](#sdk-installation-troubleshooting)
if CMake rejects the installation.


Build the SDK and set the installation path. Enter the Holoscan SDK source
directory containing `run`:

```bash
# Enter the SDK source directory containing ./run.
cd <path/to/holoscan-sdk-source>

# Build and install the SDK
./run build

# Set the installation path and ensure it is populated
export HOLOSCAN_SDK_ROOT="$(pwd)/$(./run get_install_dir)"

# Inspect the installation path reported by the SDK build helper
echo ${HOLOSCAN_SDK_ROOT}

# Return to the Holoscan Camera project
cd -
```

## Language Support

Holoscan SDK 5 operators are implemented in C++. Optional Python bindings
expose V4L2, SIPL, and Argus through `holoscan_camera.operators`, with
Python CLI build, test, capture, and live-preview support. They require a matching
Python-enabled SDK installation and CPython 3.12 or newer. See the
[Python build guide](python/README.md) for the dependency versions and setup.

## FAQ + Troubleshooting

### Integrating with custom Holoscan SDK 5.0 development

Use the local SDK workflow documented above to integrate and develop Holoscan Camera changes against Holoscan SDK 5.0 development:

1. Develop and test changes in the Holoscan SDK 5.0 project
2. Update the Holoscan SDK 5.0 installation folder to latest development
3. Rebuild Holoscan Camera against the local SDK installation as documented above

### SDK installation troubleshooting

The wrapper can auto-detect an SDK installation under `../holoscan-sdk`, but
that check does not verify whether it includes `holoscan::sensor_io`. Set
`HOLOSCAN_SDK_ROOT` explicitly to select the SDK installation you built.

If CMake finds the SDK package but reports `holoscan_FOUND` as `FALSE`, the
installation may be missing the required `sensor_io` component. Check for
`holoscan-sensor-io-targets.cmake` in the SDK installation. If it is missing,
rebuild and install your selected Holoscan SDK 5.0 source with `sensor_io`, then update
`HOLOSCAN_SDK_ROOT` and configure Holoscan Camera again.

### Incorrect SDK installation

Holoscan Camera depends on Holoscan SDK 5.0 and its CUDA 13 dependency. Earlier Holoscan installations are not
compatible. Start with clean build and installation folders and a compatible SDK source
baseline from [SDK setup](#holoscan-sdk-50-setup), then try again.
The SDK package version alone does not establish source compatibility.

## License

Apache-2.0 - see [LICENSE](LICENSE).
