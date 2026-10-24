# SIPL frame saver

Captures frames from a single SIPL camera via
[sipl_capture_op](../../operators/sipl_capture_op/README.md) and saves them to disk:
one `.raw` file per frame (exactly the bytes `SIPLCaptureOp` produced —
packed 10-bit Bayer for RAW10, or planar Y + interleaved UV for NV12) plus a
plain-text `.txt` sidecar carrying enough descriptor fields (dimensions,
pitch, encoding, Bayer phase, timestamps) to decode the raw bytes without
out-of-band knowledge. A separate `_sensor.txt` sidecar records the
`sensor_data` port's metadata for the same frame.

Waits for both the frame-saving sink and the sensor-data sink to reach the
requested frame count before stopping the session, so a completed run always
has matching `.raw` / `.txt` / `_sensor.txt` triples.

The camera is constructed with `MemoryKind::kHost`: since the only consumer
here is the filesystem, publishing straight to host memory avoids the
device round trip `SIPLCaptureOp`'s GPU-resident default would otherwise
force this app to buy back with its own copy.

## Requirements

- Requires NVIDIA Jetson AGX Thor with JetPack 7.2.1, the only
  [supported SIPL platform](../../README.md#supported-platforms) in this release
- Requires a mono or stereo VB1940 camera input via Holoscan Sensor Bridge FPGA

Experimental source builds on IGX OS 2.0 / R38.5 are not a supported
configuration. They need the
[host SIPL development prerequisite](../../operators/sipl_capture_op/README.md#igx-r385-host-prerequisite)
before using the wrapper.

## Usage

```text
Usage:
  sipl_frame_saver [OPTIONS]

Options:
  --camera-config NAME   SIPL camera configuration name (default: ov2311_raw)
  --json-config PATH     Path to a vendor JSON platform config file (optional)
  --camera-index N       Zero-based camera index within the rig (default: 0)
  --cuda-device N        CUDA device ordinal for NvSci buffer import (default: 0)
  --frames N             Number of frames to save then stop (default: 5)
  --output-dir DIR       Output directory; created if absent (default: /tmp/sipl_frames)
  --isp                  Request NV12/ISP output instead of RAW10 (raw_output=false)
  --timeout-s SEC        Seconds to wait for --frames to complete (default: 60)
  -h, --help             Show this help text
```

The sample configs in [`applications/config/sipl`](../config/sipl) (`vb1940_single.json`,
`vb1940_dual.json`, `vb1940_stereo.json`) all run the VB1940 at 30 FPS.

## Run

```bash
./holoscan_camera run sipl_frame_saver --run-args \
  '--camera-config VB1940 --json-config applications/config/sipl/vb1940_single.json --frames 300'
```

Set the camera MAC address in the JSON config to match your connected camera
before running. The CLI launches the application from the repository root, so
relative `--json-config` and `--output-dir` paths resolve from that directory.
For container runs, the application metadata runs the container privileged:
NvSIPL reads `/proc/device-tree/model` when it loads the camera query database,
which Docker hides from unprivileged containers, and opening the camera needs
device access they don't have.

The `./holoscan_camera` wrapper selects the pinned CLI 5 version automatically.
On R38.5 IGX hosts, it preserves caller-supplied `--docker-opts` while adding
the matching SIPL source mount. Options given with `--docker-opts` add to the
metadata's `--privileged`.

## Decoding

```bash
python3 tools/decode_sipl_frame.py /tmp/sipl_frames/frame_00000001.raw --out out.png
```
