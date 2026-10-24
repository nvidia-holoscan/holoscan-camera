# Holoscan Camera Release Notes

## Release Artifacts

Holoscan Camera 1.0.0 extends Holoscan SDK 5.0 with C++ and Python camera
operators. Use the artifact and backend supported by your host BSP and camera.

- **Documentation:** [Camera setup and supported platforms](README.md).
- **Python distribution:** `holoscan-camera-cu13`, with the companion
  `holoscan-core-cu13` runtime; see the [Python guide](python/README.md).
- **C++ distribution:** `holoscan-camera` Debian package and installed CMake
  targets; see [build, test, and consume](README.md#build-test-and-consume).

Package names identify the release formats; check the selected distribution
channel for availability. Source and binary builds require CUDA 13 and a
compatible SDK installation containing `holoscan::sensor_io`. See
[SDK setup](README.md#holoscan-sdk-50-setup) for prerequisites.

## 1.0.0

Holoscan Camera's first general-availability release provides V4L2, SIPL, and
Argus capture operators for native SDK graphs, Python operator facades, and
reference applications for capture, visualization, and stereo diagnostics.

### New Features and Improvements

#### Capture operators

- **V4L2:** `V4l2CaptureOp` captures packed YUYV frames from Linux camera
  devices into host, pinned-host, or CUDA-device memory. See the
  [V4L2 guide](operators/v4l2_capture_op/README.md).
- **SIPL:** `SIPLCaptureOp` publishes RAW10/NV12 images and sensor metadata from
  NvSIPL-managed cameras on Jetson AGX Thor with JetPack 7.2.1. Multiple
  operators can share one `SIPLCaptureService` for a camera rig. See the
  [SIPL guide](operators/sipl_capture_op/README.md).
- **Argus:** `ArgusCaptureOp` publishes ISP-processed Jetson camera images and
  sensor metadata with bounded native buffers. See the
  [Argus guide](operators/argus_capture_op/README.md).

#### Python support

The `holoscan_camera` package exposes all three operator APIs through the
SDK's authoring registry. The SDK discovers the same package through its
`holoscan.camera` alias. Capture and buffer ownership remain in C++;
`SIPLCaptureService` and its value types are directly bound by the SIPL native
extension. Typing declarations accompany the APIs. See
[facades, native extensions, and typing](python/README.md#facades-native-extensions-and-typing).

Separate V4L2, Argus, and SIPL native extensions let portable V4L2 imports work
without loading optional BSP libraries. Requesting an optional API loads that
backend immediately; missing extensions or BSP libraries can raise `ImportError`.
Wildcard imports and attribute probes can request optional backends too.
An advertised name or typing declaration does not establish runtime support.

#### Reference applications

- [`holoscan_camera_v4l2`](applications/holoscan_camera_v4l2/README.md)
  validates graphs and captures V4L2 frames; its Python version also provides
  live preview through Holoviz.
- [`holoscan_camera_argus`](applications/holoscan_camera_argus/README.md)
  receives Argus frames and metadata.
- [`sipl_frame_saver`](applications/sipl_frame_saver/README.md) saves SIPL
  frames and metadata, while
  [`sipl_stereo_monitor`](applications/sipl_stereo_monitor/README.md) reports
  per-camera progress and cross-camera timing.
- [`sipl_player`](applications/sipl_player) displays an NvSIPL camera rig in a
  tiled HoloViz window or separate windows (`--separate`), using ISP output or
  GPU-demosaiced RAW10 (`--raw`). C++ and Python versions are available; the
  CLI selects Python by default, or C++ with `--language cpp`.

### Breaking and Behavior Changes

#### C++ namespace, metadata payload names, and library ABI

The module's C++ namespace is now `holoscan::camera`, formerly
`holoscan::holoscan_camera`, matching the `holoscan.camera.*` names used in
Python. The metadata payloads follow it: `holoscan.camera.SIPLFrameMetadata`
and `holoscan.camera.ArgusFrameMetadata`, formerly
`holoscan.holoscan_camera.*`. Update `holoscan::holoscan_camera` qualifiers
and namespace aliases, and any code or recordings that refer to the payloads
by name.

Operator library SONAMEs follow the module major version and change from
`.so.0` to `.so.1` (for example, `libv4l2_capture_op.so.1`). Rebuild or relink
applications built against 0.x libraries.

#### SIPL operator construction

`SIPLCaptureOp` requires its shared `SIPLCaptureService` and camera index at
construction. Replace the removed `SIPLCaptureOpParams` / `set_params()` path:

```cpp
auto camera = graph.op<SIPLCaptureOp>("camera", holoscan::MemoryKind::kHost);
camera.set_params(SIPLCaptureOpParams{.service = service, .camera_index = 0U});
```

with:

```cpp
auto camera = graph.op<SIPLCaptureOp>(
    "camera", service, /*camera_index=*/0U, holoscan::MemoryKind::kHost);
```

The service must be non-null. `memory_kind` remains an optional final argument
and defaults to `holoscan::MemoryKind::kCudaDevice`. Multiple operators can
share the same service; graph constructor captures retain its shared lifetime.
Use the Holoscan SDK 5.0 constructor-capture and schema-generation APIs when
rebuilding; early-access SDK revisions with the same `5.0.0` package version
may lack those APIs. Schema generation requires the `SCHEMA`,
`COMPATIBILITY_EPOCH`, and `MAX_SERIALIZED_SIZE` helper arguments as well as
shared-pointer constructor captures. See [SDK setup](README.md#holoscan-sdk-50-setup).

#### ArgusCaptureOp default frame delivery

The default `drop_policy`, `kDropOldest`, now selects the newest queued frame
on **every compute activation**, during both startup and steady state. Older
queued frames are discarded even when the queue is not full. Previously,
compute consumed queued frames in FIFO order, and this policy discarded an
old frame only when the completed-frame queue was full.

This releases native capture buffers sooner to prevent a persistent backlog
from reducing capture throughput and increasing latency. Existing applications
using the default configuration may receive fewer frames after a consumer
delay, including brief steady-state jitter. Recording or encoding applications
that previously received those queued frames should review their delivery
requirements when upgrading.

To retain queued frames for FIFO consumption, explicitly set
`drop_policy = ArgusDropPolicy::kDropNewest`. This retains the latency/backlog
tradeoff and rejects incoming frames when the queue is full. It does **not**
guarantee lossless recording: tensor-pool exhaustion and publication
backpressure can also drop frames. See the
[Argus memory and backpressure guide](operators/argus_capture_op/README.md#memory-and-backpressure)
for queue behavior and drop counters.

#### SIPL timestamps and frame waits

For supported HSB Camera-over-Ethernet inputs, the published image timestamp
uses HSB first-data time projected into the graph clock. It is not a calibrated
optical exposure-start timestamp. Frames with an unusable HSB timestamp are
skipped rather than assigned a fallback Tegra timestamp; the next published
frame is marked degraded. A continuous rejection window of 30 seconds fails
the run, checked as frames arrive; a stream that stops delivering frames is
handled by the frame-wait timeout instead. Maintain PTP synchronization and
avoid host clock steps during capture. See
[SIPL timestamp semantics](operators/sipl_capture_op/README.md#siplcaptureop).

The default `SIPLCaptureService.timeout_us` is 3,000,000 microseconds (3 seconds)
in C++ and Python. This bounds a wait for the next frame; it is separate from
`sipl_stereo_monitor`'s startup, stall, and overall timeouts.

### Build and Packaging

- **Component selection:** `HOLOSCAN_CAMERA_BUILD_ALL` replaces the old
  all-components option and defaults to `OFF`. Enable individual applications
  or operators, or opt into all components on a compatible host. V4L2-only
  builds avoid unrelated Argus and SIPL development dependencies.
- **Installed CMake consumers:** link `holoscan::camera` for all enabled
  Camera operators. Installation provides `holoscan-camera-config.cmake` under
  `<libdir>/cmake/holoscan-camera` and exported targets under
  `<libdir>/cmake/holoscan`. Operator install rules use the `holoscan-camera`
  component.
  The installed package configuration finds the SDK when the consumer has not
  already configured it. Nested builds install into the parent SDK layout and
  run CPack only when
  `HOLOSCAN_CAMERA_BUILD_DEB=ON`.
- **Python wheels:** the distribution requires CPython 3.12 or newer and the
  matching Core CUDA 13 package. Native wheels use the `cp312-abi3` ABI;
  CI validates and tags them as `manylinux_2_39` for x86_64 or ARM64. Wheels
  carry Camera libraries and typing files; system CUDA libraries and camera
  drivers remain host prerequisites. See [Python wheel support](README.md#python-wheel-support).
- **Backend coverage:** x86_64 wheels provide native V4L2 support. ARM64 wheels
  include V4L2, R39 SIPL API v2, and Argus. SIPL wheel support targets Jetson AGX
  Thor with JetPack 7.2.1; Argus targets Jetson AGX Orin. V4L2 remains
  usable on SBSA, DGX Spark, and R38 without loading optional backends.
- **R38 SIPL source builds (experimental):** IGX OS 2.0 / R38.5 uses matching
  SIPL API v1 development headers and runtime libraries, supplied separately. Set
  `HOLOSCAN_CAMERA_SIPL_SOURCE_DIR` to the installed source tree for the wrapper
  to mount it read-only. SIPL targets default off on R38. These builds are not
  a supported SIPL configuration, and R38 SIPL is unsupported by the wheel. See
  the [R38.5 prerequisite](operators/sipl_capture_op/README.md#igx-r385-host-prerequisite).

### Holoscan CLI Wrapper

The wrapper installs Holoscan CLI **5.0.0** from
[`requirements-cli.txt`](requirements-cli.txt), which also selects the version
in development images. Run `./holoscan_camera version` to check the installed
version. Earlier prerelease CLI exports are no longer required.

- Use Python 3.11 or newer for the CLI, or an activated compatible virtual
  environment when the system interpreter is older. Camera's Python bindings
  and wheels separately require Python 3.12 or newer.
- Edit `requirements-cli.txt` and rebuild development images to change the CLI
  pin. `HOLOSCAN_CLI_PINNED_VERSION` no longer selects it.
  `HOLOSCAN_CLI_INSTALL_ARGS` adds pip options to the required installation.
- Project naming, the CUDA 13 default, the CTest driver, and base images are
  configured in `pyproject.toml`. Select a compatible SDK image as described in
  the [developer guide](DEVELOPER.md#holoscan-sdk-baseline).
- The CLI selects the SDK from `--local-sdk-root`, `HOLOSCAN_SDK_ROOT`, nearby
  SDK installations, then the container's SDK. The wrapper also accepts
  `HOLOSCAN_SDK_INSTALL_DIR` as an alias for `HOLOSCAN_SDK_ROOT`.

### Bug Fixes

| Issue | Component | Description |
| --- | --- | --- |
| 6800245 | Build | Fixed V4L2 container builds on IGX R38.5 by skipping unavailable SIPL and Argus development-header downloads. SIPL source builds still require matching R38 development headers. |
| 6843559 | Build | Fixed V4L2 test configuration on IGX Thor iGPU / L4T R38.5 failing on missing `Argus/Argus.h`. Component-wide builds default off, so selecting V4L2 does not enable unrelated Argus targets. |
| 6840016 | Build | Fixed V4L2 configuration on DGX Spark failing on the unavailable `nvargus_socketclient` library. The same component-selection fix keeps Argus and SIPL builds off the V4L2 build path. |
| — | Build | Fixed duplicate CMake argument-keyword warnings when configuring the Debian package from a parent scope that already defines `oneValueArgs`. |
| — | SIPL | SIPL ISP capture now waits on the ISP completion queue and drains RAW metadata separately, preventing completed ISP frames from accumulating while waiting for a new RAW frame. |
| — | Argus | Added `libgles2` to the development container so Argus validation can load `libGLESv2.so.2` on Jetson AGX Orin. |
| — | CLI | `./holoscan_camera test` now forwards `SIPL_CAMERA_CONFIG`, `SIPL_JSON_CONFIG`, `SIPL_CAMERA_INDEX`, and `SIPL_CUDA_DEVICE` to the test container. Previously the SIPL hardware tests skipped because these variables did not reach it. |
| — | SIPL | Fixed SIPL buffer lifetimes, matched-metadata preservation, RAW image offset, and active height. |
| — | SIPL | Aligned the Python `SIPLCaptureService.timeout_us` default with the native 3,000,000 microseconds (3 seconds), replacing the Python binding's 1-second default. |

### Known Limitations

**SIPL platform scope:** `SIPLCaptureOp` is supported only on Jetson AGX Thor
with JetPack 7.2.1 (R39.2) in this release. SIPL capture on Jetson Orin and on
IGX Thor T5000 is not part of this release. Users who need SIPL on IGX Thor T5000
can install JetPack 7.2.1
(6953514). IGX Thor T7000 has no
SIPL hardware support. IGX OS 2.0 / R38.5 SIPL source builds remain experimental. See
[Supported platforms](README.md#supported-platforms).

**V4L2 capture quality (6744108):**
affected camera/USB configurations can report degraded or driver-flagged
corrupt frames, sequence loss, and capture timeouts. Direct V4L2 capture on
IGX Thor also reproduced lost frames without Holoscan. Increasing the buffer
count helped individual runs but did not establish a general fix. Inspect
sample quality flags and reject invalid frames; see
[counter semantics](operators/v4l2_capture_op/README.md#capture-counters) and
[recorded qualification results](operators/v4l2_capture_op/benchmarks.md).

### Known Issues

| Issue | Component | Description |
| --- | --- | --- |
| 6801049 | SIPL | Capture from a single mapped VB1940 camera can fail on Jetson, including Jetson AGX Thor. Reports include device-tree access and camera-database parsing errors; the single-camera failure remains under investigation separately from stereo startup timing. |
| 6934123 | SIPL | VB1940 stereo capture on Jetson AGX Thor with JetPack 7.2.1 can exceed `sipl_stereo_monitor`'s default 15-second startup timeout. Set `--startup-timeout-s 40`; this allowed the reported capture test to pass. It changes the application's startup allowance, not the service's per-frame wait, and does not establish a fix for intermittent startup stalls. |
| 6854954 | SIPL | On Jetson Thor with Jetson Linux R39.2.1 and ISP enabled, synchronized VB1940 frames can report capture-start timestamps about 18 ms apart. This metadata discrepancy was reproduced in the native SIPL sample; the RAW-only control had close capture-start timestamps. It can mislead timestamp-based stereo checks and fusion. It does not establish physical exposure skew, and no common cause with the separate delivery delay in 6854955 has been established. |
| 6714027 | SIPL | Stereo-synchronized SIPL capture with HSB VB1940 cameras can intermittently fail to start or stall, including on JetPack 7.2.1. Initial native-sample tests on JetPack 7.2.0 and 7.2.1 recorded 11–16 failures per 100 runs, with frames stopping within roughly the first five seconds. Streams reaching ten seconds remained stable in those tests; this observation is not a stability guarantee. Investigated Camera over Ethernet (CoE) failures include fatal capture timeouts following a PTP clock step during capture. Confirm PTP lock before starting capture to mitigate the clock-step failure path, and continue monitoring stream health. Separate ISP failures were also observed without PTP, so this is not a general workaround for startup stalls. See the [SIPL benchmarks and qualification results](operators/sipl_capture_op/benchmarks.md) for historical measurements. |
| 6854955 | SIPL | On Jetson Thor with Jetson Linux R39.2.1, synchronized VB1940 stereo capture at 30 FPS can deliver the secondary camera frame about one frame period (33 ms) after the primary. The completion-queue receipt delay was reproduced with the native SIPL sample, including RAW-only output and independent readers, without Holoscan in the capture path. Receipt time was recorded immediately after the application's completion-queue `Get()` returned; internal enqueue time was not measured, leaving internal staging versus reader wake latency unresolved. This finding is distinct from the intermittent approximately 18 ms capture-start timestamp discrepancy in 6854954; no common cause is established. It adds stereo-pair latency even when throughput remains approximately 30 FPS; it does not establish sensor capture-time skew or ISP serialization. Qualify stereo-pair delivery latency for the application; no workaround preserving synchronization has been verified. |
