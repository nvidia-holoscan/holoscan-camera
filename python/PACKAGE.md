<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Holoscan Camera Python support

Holoscan Camera exposes native camera capture operators to Holoscan SDK 5
Python graphs. Capture, buffer ownership, and device lifecycle remain in C++.
Python applications use the SDK's typed image payloads and tensor APIs.

Import operators from `holoscan_camera.operators`. The SDK also discovers the
package through the `holoscan.camera` alias. A Python operator facade loads its
backend and resolves a Core registry proxy; it does not implement capture.
Wheel builds configure facades and typing declarations for all three backends.
Usability depends on the wheel's native extensions, host hardware, and runtime
libraries. An advertised name or `.pyi` declaration is not a capability check.
`SIPLCaptureService` and its related value types are bound directly by `_sipl`.

The default wheel build includes V4L2. Running capture requires a compatible
camera, the matching Holoscan Core CUDA 13 package, and the platform's native
runtime libraries. Wheels do not bundle camera drivers or the system CUDA
runtime. Install the artifact qualified for your target platform.

Source builds require CMake 4+, a C++20 toolchain, CPython 3.12+, and a matching
Holoscan SDK development installation with Python support and its exported
Python build helpers. Build and application instructions are provided in the
source distribution's `python/README.md` and application directories.

The ARM64 wheel includes V4L2 and separate R39 SIPL v2 and Argus extensions.
V4L2 remains usable on SBSA/DGX Spark and R38 without loading those backends.
R39 SIPL is supported only on Jetson AGX Thor with JetPack 7.2.1; R39 Argus
requires Jetson Orin.
The x86_64 wheel supports V4L2. Unsupported backend imports may fail; wildcard
imports request all backends. Attribute probes such as `hasattr()` and
`inspect.getmembers()` can also request a backend and propagate `ImportError`.
R38 SIPL is not supported by the wheel.
