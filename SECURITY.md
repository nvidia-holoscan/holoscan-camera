# Security Policy: Holoscan Camera

## Reporting a Vulnerability

If you discover a potential security vulnerability, **do not open a public issue,
merge request, or discussion**.

- **Web (preferred):** Report it through the
  [NVIDIA Vulnerability Disclosure Program](https://www.nvidia.com/en-us/security/).
- **Email:** Send details to [psirt@nvidia.com](mailto:psirt@nvidia.com). For
  encrypted communication, use the
  [NVIDIA public PGP key](https://www.nvidia.com/en-us/security/pgp-key).
- **GitLab:** Use this repository's **Security** tab to submit a private report
  on `holoscan/holoscan-camera`.

Include the project name and affected version or branch, vulnerability type,
reproduction steps, proof-of-concept code when available, and an impact
assessment. Detailed reports help NVIDIA evaluate and address issues faster.

NVIDIA's Product Security Incident Response Team (PSIRT) will acknowledge the
report, validate and assess the issue, develop and test fixes, and publish a
security bulletin when appropriate.

## Supported Versions

Security fixes are applied to the current `main` branch. Holoscan Camera 1.0.0
requires Holoscan SDK 5.0.0 or newer, as declared in `metadata.json`.

## Security Architecture and Context

Holoscan Camera is a C++ library and set of sample applications that capture
camera frames into Holoscan SDK 5 graphs. `V4l2CaptureOp` reads Linux V4L2
devices, `SIPLCaptureOp` captures from NvSIPL-managed cameras, and
`ArgusCaptureOp` captures ISP-processed images through NVIDIA `libargus`.
Sample programs under `applications/` open those operators, and
`sipl_frame_saver` writes captured frames to disk.

This project operates at the library and sample-application level. Its primary
security responsibility is to keep camera frames, device buffers, and
caller-supplied capture configuration inside the process and files the operator
intended. It does not authenticate users, authorize device access, or provide a
network service.

The principal security boundaries are:

- Callers choose the V4L2 device path (`holoscan_camera_v4l2 --device`, default
  `/dev/video0`), the SIPL platform JSON (`--json-config` or `SIPL_JSON_CONFIG`),
  the NITO directory, the CUDA device, and the frame output directory.
- `v4l2_device.hpp` opens that path with `O_RDWR` and maps driver buffers with
  `mmap` (`MAP_SHARED`, read/write). The public operator header does not expose
  `linux/videodev2.h`.
- `SIPLCaptureService` passes the JSON path to NvSIPL `ParseJsonFile` and loads
  ISP tuning files named from that configuration (`load_nito_file`). Checked-in
  configs under `applications/config/sipl/` name sensor addresses, including a
  CoE camera IP and MAC, and a `cryptoConfigName` that NvSIPL interprets.
- `sipl_frame_saver` writes raw frame bytes and metadata under `--output-dir`
  (default `/tmp/sipl_frames`). `tools/decode_sipl_frame.py` decodes those files
  locally.
- The development `Dockerfile` and `tools/install_argus_build_deps.sh` download
  Jetson SIPL and Argus build inputs.
- The Debian package depends on Holoscan and dynamically links NVIDIA camera,
  CUDA, and EGL libraries. It does not bundle those libraries.

### Threat Model

1. **Hostile or mis-bound V4L2 device:** `V4l2CaptureOp` opens the caller-supplied
   path and shares memory with the driver. A device node the process should not
   open, or a driver that returns buffers larger than the negotiated
   `sizeimage`, can expose or corrupt the capture process. The operator rejects
   a negotiated image larger than the capture buffer it allocated; it does not
   decide which device nodes the process may open.
2. **Untrusted SIPL JSON, NITO files, and camera endpoints:**
   `SIPLCaptureService` parses the platform JSON and reads each NITO file fully
   into memory from `nito_base_path_` plus the module name. A JSON or NITO path
   chosen by an untrusted caller can point capture at an unintended sensor,
   including the network address in a CoE config, or force a large allocation.
   This module does not authenticate the camera or verify the JSON or NITO
   contents.
3. **Camera-frame disclosure through sample output:** `sipl_frame_saver` writes
   raw frames to a directory that defaults to `/tmp/sipl_frames`, and
   `tools/decode_sipl_frame.py` writes decoded images beside the input. On a
   multi-user host those files can be readable by other local users unless the
   operator chooses a private directory and permissions.
4. **Build-input substitution:** The image build downloads the Jetson SIPL API
   archive from `developer.nvidia.com` without a pinned checksum.
   `install_argus_build_deps.sh` checks Argus package hashes against the
   Packages index fetched from the same Jetson apt repository. A compromised
   download host or index can enter the development image before the camera
   libraries are compiled.
5. **Capture-buffer lifetime across CUDA and Argus:** SIPL registers NvSIPL
   buffers against CUDA pointers in `pending_outputs_`, and Argus capture links
   `libnvargus_socketclient`, `libnvbufsurface`, and EGL for buffer sharing. A
   use-after-free or size mismatch at that boundary is a memory-safety bug in
   the capture process, not a separate network service.

### Critical Security Assumptions

- The host OS, container runtime, and device permissions allow the process to
  open only the camera nodes, Argus socket, and GPU devices intended for that
  deployment.
- The Linux V4L2 driver, NvSIPL, Argus, CUDA, and the Jetson BSP behave as
  trusted platform software and enforce their own buffer and device contracts.
- The Holoscan SDK checks tensor and schema bounds for downstream consumers of
  frames this module publishes.
- Device paths, SIPL JSON, NITO directories, output directories, and environment
  variables such as `SIPL_JSON_CONFIG` are operator configuration, not
  untrusted network input.
- CoE or other network-attached cameras named in platform JSON sit on a network
  the operator controls. This module does not encrypt or authenticate that path
  itself.
- Development-image downloads come from NVIDIA-operated HTTPS endpoints. Argus
  package bytes match the hash published in the Jetson repository index fetched
  at build time.
- Secrets are supplied by the deployment environment and are not committed to
  the repository.

## Dependency and Distribution Security

New or upgraded third-party dependencies must have their license and
redistribution terms reviewed before integration. Components distributed with
the module must follow the applicable NVIDIA Open Source Review Board process
and be named in `NOTICE`, which the build installs with the `holoscan-camera`
component. NVIDIA camera, CUDA, and BSP libraries are dynamic dependencies of
the package, not copies shipped inside it.
