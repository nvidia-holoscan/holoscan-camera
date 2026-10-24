# SIPL capture operator

Holoscan SDK 5.x camera capture operator for NvSIPL-managed cameras on
Jetson AGX Thor. Ported from Holoscan Sensor Bridge's `SIPLCaptureService`,
wired to HSDK5 lifecycle hooks, `holoscan::sensor_io` schemas, and a configurable
frame placement (host or CUDA-device). Requires matching NVIDIA NvSIPL
development headers (`NvSIPLCamera.hpp`) to build. No dependency on Holoscan Sensor Bridge,
with exceptions:

1. the SIPL driver stack may use HSB as one possible underlying driver, not
   directly exposed to `SIPLCaptureOp`;
2. SIPL frames from HSB inputs leak some HSB-specific metadata details. We
   handle these directly with static metadata details derived from the HSB
   project sources.

## Files

| File | Purpose |
| --- | --- |
| `sipl_capture_op.hpp` / `.cpp` | `SIPLCaptureOp` — one operator instance per camera |
| `sipl_capture_service.hpp` / `.cpp` | `SIPLCaptureService` — owns the NvSIPL pipeline; shared across cameras in a rig |
| `sipl_compat.hpp` | SIPL API v1/v2 compatibility shims (`NVSIPL_API_MAJOR_VERSION`) — see [Supported versions](#supported-versions) |
| `hsb_frame_metadata.hpp` | Parses HSB metadata embedded in the frame buffer |
| `tsc_to_ns.hpp` | Converts the Tegra TSC tick counter to nanoseconds |
| `sipl_frame_metadata.fbs` | FlatBuffers schema for the `sensor_data` output port |
| `operator_catalog.hpp` / `.cpp` | Authoring-registry row through which the [Python bindings](#python) construct the operator |
| `sipl_capture_service_handle.hpp` / `.cpp` | The constructor-handle type that carries a `SIPLCaptureService` into `SIPLCaptureOp`'s registry row |
| `python/` | The Python facade and its committed stub, the provider's SIPL bindings, the CuPy converters (`holoscan_camera.operators.converters`), and the [Python guide](python/README.md) and tests |
| `tests/` | Unit tests (no camera needed) and hardware integration tests |

## Supported versions

The default environment supports Jetson AGX Thor with JetPack 7.2.1 / L4T R39.2
and SIPL API v2, the only supported SIPL platform in this release. IGX OS 2.0 /
L4T R38.5 source builds are experimental and not supported; they need an R38.5
IGX host with its matching SIPL development tree installed in advance. The
R38.5 host BSP supplies the runtime libraries through `nvidia-l4t-camera`, but
its APT repositories do not supply the SIPL development headers.

The container build's `L4T_VERSION` build-arg (see [`Dockerfile`](../../Dockerfile))
defaults to `39.2.0`, matching the JP7.2.1 target above. On R38.5, the wrapper
selects the host BSP version but the container intentionally skips the SIPL
download; R39 headers must not be used to build against an R38 runtime.

### IGX R38.5 host prerequisite

Complete this pre-step on the R38.5 IGX host before invoking
`./holoscan_camera` for a SIPL target:

```bash
curl -fLO \
  https://developer.nvidia.com/downloads/igx/v2.0/Jetson_SIPL_API_R38.5.0_aarch64.tbz2
sudo tar xjf Jetson_SIPL_API_R38.5.0_aarch64.tbz2 -C /
test -f /usr/src/jetson_sipl_api/sipl/include/NvSIPLCamera.hpp
```

The wrapper recognizes an R38.5 IGX host and mounts
`/usr/src/jetson_sipl_api` read-only at
`/opt/holoscan-camera/jetson_sipl_api` in the container for
explicit SIPL build, run, and test commands. CMake prefers this tree over
CLI 5's automatic host SIPL mount. If the archive is extracted
elsewhere, point the wrapper at the directory containing `sipl/`:

```bash
export HOLOSCAN_CAMERA_SIPL_SOURCE_DIR=/absolute/path/to/jetson_sipl_api
```

An explicitly set path must contain `sipl/include/NvSIPLCamera.hpp`; otherwise
the wrapper exits before starting the container. SIPL targets default off on
R38.5, so enable the required application or operator explicitly. V4L2-only
builds remain independent of this prerequisite.

## SIPLCaptureOp

| Port | Type | Description |
| --- | --- | --- |
| `frame` | `holoscan::schema::ImageT` | RAW10 (Bayer) or NV12 frame |
| `sensor_data` | `SIPLFrameMetadataT` | Per-frame TSC timestamps, sequence, HSB metadata when present |

For supported HSB CoE cameras, `capture_timestamp_ns` in the Image header and
both sample envelopes uses HSB first-data time, projected into the graph clock.
It marks data reaching the FPGA, not host reception or a calibrated optical
exposure event. This departs from the HSDK5 Image schema's integration-start
convention. Do not derive exposure midpoint from this header and exposure duration.
Non-HSB cameras retain SIPL capture-end time; mixed transports do not share an
optical timestamp convention.

HSB requires continuously maintained [NVIDIA host PTP setup](https://docs.nvidia.com/holoscan/sensor-bridge/getting-started/host-setup),
with the transmitting PHC synchronized to `CLOCK_REALTIME` using `phc2sys -O 0`.
The operator uses a frame's HSB timestamp only if it is within one second of host
time when the operator processes the frame. That check does not prove PTP lock or
convergence, and it cannot tell an unsynchronized HSB from a delay: a correctly
timestamped frame that waited more than a second, for example in a queue through
a stall, is rejected too. A frame without a usable HSB timestamp (missing,
invalid, or outside that second) is skipped, with a warning after startup, and
the next frame the operator publishes is marked degraded, as after a frame SIPL
dropped. The run fails only if frames keep being rejected for 30 seconds: that
window starts with the first rejected frame, a usable frame ends it, and it is
checked as frames arrive, so a capture that stops delivering frames fails on the
frame wait (`timeout_us`) instead. At startup, it is the time HSB has to reach
host time.
There is no fallback to Tegra timestamps. The operator does not monitor PTP
health. Keep PTP running and avoid host realtime clock steps during a session,
since the graph-clock offset is measured once.

The `sensor_data` metadata also forwards SIPL's `frameCaptureStartTSC` and
`frameCaptureTSC` as `frame_capture_start_tsc` and `frame_capture_end_tsc`.
Both are raw ARM Generic Timer ticks, not nanoseconds or buffer delivery times.
SIPL reports exposure duration separately in `exposure_time`; it is
not a frame-capture duration and cannot establish an exposure midpoint from
capture end alone. The raw start and end ticks remain available for diagnostics.

### Constructor

```cpp
explicit SIPLCaptureOp(
    std::shared_ptr<SIPLCaptureService> service,
    std::uint32_t camera_index,
    holoscan::MemoryKind memory_kind = holoscan::MemoryKind::kCudaDevice);
```

`service` is the shared `SIPLCaptureService` managing the camera rig. The
graph retains it as part of the operator factory, and each constructed
operator shares its lifetime. `camera_index` selects the operator's camera
within that rig and is validated during discovery.

`memory_kind` selects where the published frame is allocated: `kHost`, `kPinnedHost`, or
`kCudaDevice` (default). This is a constructor argument because `setup()`
freezes the placement into the frame port contract. Pick the
placement your own consumer needs: a GPU-resident consumer wants the
default `kCudaDevice`, and a host-only consumer (e.g. writing frames to
disk, as in [sipl_frame_saver](../../applications/sipl_frame_saver/README.md)) should
request `kHost` or `kPinnedHost` rather than paying its own device-to-host
copy downstream. `kCudaDevice` additionally requires the application to
bind a device via `CompileOptions::deployment.bind_tensor_output_device()`;
the binding must be *absent* for the two host kinds.

```cpp
auto camera = graph.op<SIPLCaptureOp>(
    "camera", service, /*camera_index=*/0U, holoscan::MemoryKind::kHost);
```

Multiple `SIPLCaptureOp` instances can share one `SIPLCaptureService` for a
multi-camera rig (see [sipl_stereo_monitor](../../applications/sipl_stereo_monitor/README.md));
the service starts streaming when the first operator arms and tears down
when the last one stops.

## SIPLCaptureService

Owns the NvSIPL pipeline: device discovery, buffer pool allocation, and the
capture thread. Constructed once per rig and shared by every `SIPLCaptureOp`
in it:

```cpp
auto service = std::make_shared<SIPLCaptureService>(
    camera_config,       // SIPL camera configuration name, e.g. "VB1940"
    json_config,          // vendor JSON platform config path (optional for single-sensor)
    raw_output,           // true = RAW10 Bayer, false = NV12/ISP
    capture_queue_depth,  // default 4
    nito_base_path,       // default "/var/nvidia/nvcam/settings/sipl"
    timeout_us,           // default 3,000,000: how long to wait for a camera's next frame
    cuda_device);          // default 0; set for the GPU that will consume frames on multi-GPU (IGX dGPU) systems
```

## Python

With Python enabled (`HOLOSCAN_CAMERA_BUILD_PYTHON=ON`), the Camera Python provider exposes
`holoscan_camera.SIPLCaptureService` and the registered operator
`holoscan_camera.operators.SIPLCaptureOp`, which takes its service as the
`service` constructor handle, with `camera_index` and `memory_kind` (`"device"`,
`"pinned"`, or `"host"`). See the [SIPL Python bindings](python/README.md)
for the build and the API,
[sipl_capture](../../applications/sipl_capture/README.md) for a capture sample,
and the Python version of
[sipl_player](../../applications/sipl_player/README.md#python-version) for a
viewer with HoloViz.

The operator library registers its row and defines the handle type, so it needs a
Holoscan SDK with constructor handles.

## Buffer ownership

In ISP mode, the service copies the optional HSB metadata from each completed RAW
buffer and releases RAW before waiting for ISP. The acquisition worker blocks only
on the ISP completion queue and drains RAW completions without blocking before and
after that wait, so RAW capture slots are freed as soon as they complete and a
backlog of finished ISP frames cannot build up behind a wait for the next RAW.
RAW and ISP dequeue order is not
a frame identity: metadata is matched by exact, nonzero capture-start TSC using
a history bounded by `capture_queue_depth`. Missing matches produce
`hsb_valid=false`, with a rate-limited debug count. No RAW image copy is added.
HSB fields come from the last bottom-embedded row exposed by SIPL on CoE cameras,
not image-buffer padding. `hsb_valid` means a record with a nonzero first-data time
and valid nanosecond fractions was read and associated; it does not mean PTP is synchronized
or that first-data time equals optical exposure time. HSB frame counters can have
different startup offsets across cameras; do not pair stereo images by them alone.

The operator still copies image pixels into a Holoscan-owned tensor so downstream
consumers do not retain SIPL capture slots. It waits for that copy to finish on
the operator's CUDA stream before releasing the source. ISP metadata is copied
by value before release.

## Tests

HSB hardware tests require the PTP setup above, running throughout the test.

```bash
./holoscan_camera test sipl_capture_op --language cpp --ctest-options "-L unit"   # no hardware needed
SIPL_CAMERA_CONFIG=<name> ./holoscan_camera test sipl_capture_op --language cpp \
  --docker-opts=--privileged --ctest-options "-L hardware"
```

Name the operator: `test holoscan-camera` builds no component unless
`HOLOSCAN_CAMERA_BUILD_ALL` is on. The hardware tests need a privileged container,
like the SIPL applications, whose metadata asks for one: NvSIPL reads
`/proc/device-tree/model`, which Docker hides from unprivileged containers, and
opening the cameras needs device access they don't have.

`sipl_operator_catalog_test` covers the registry row without a camera. The hardware tests skip when `SIPL_CAMERA_CONFIG` is unset. The wrapper forwards
`SIPL_CAMERA_CONFIG`, `SIPL_JSON_CONFIG`, `SIPL_CAMERA_INDEX`, and
`SIPL_CUDA_DEVICE` into the test container when they are set (see
[`pyproject.toml`](../../pyproject.toml)). `SIPL_JSON_CONFIG` must name a path
inside the container, such as a file under `/workspace/holoscan_camera`.

See downstream applications for full working examples:
[sipl_player](../../applications/sipl_player/README.md) (every camera of a
configuration, shown with HoloViz),
[sipl_frame_saver](../../applications/sipl_frame_saver/README.md) (single camera,
save to disk) and [sipl_stereo_monitor](../../applications/sipl_stereo_monitor/README.md)
(two cameras, one shared service). The frame saver and the stereo monitor default
to `kHost` output. `sipl_player` and the stereo monitor's `--gpu` mode are
device-output capture examples: they select `kCudaDevice` and bind the frame
outputs to the CUDA device. `SIPLCaptureOpCompileTest` provides additional compile
coverage in
[tests/sipl_capture_op_test.cpp](tests/sipl_capture_op_test.cpp).

## Benchmarks

See the [SIPL benchmarks and qualification results](benchmarks.md) for recorded
stereo-sync stability and camera-firmware observations.

## FAQ

**Wrong `image_bfbs_generated.h` picked up at build time?** Mixing headers
from two different Holoscan SDK installs on the same include path (e.g. a
stale `install/` dir reused across an SDK pull) is unsupported and produces
undefined behavior. Wipe and reinstall the SDK (`./run clear_cache` in
`holoscan-sdk`) rather than trying to fix include ordering downstream.
