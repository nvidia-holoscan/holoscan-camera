# holoscan-camera package

This directory defines CPack TGZ and direct Debian packaging for
`holoscan-camera`. Both use the FHS `/usr` install contract.

## Usage

```bash
./holoscan_camera package holoscan-camera --pkg-generator DEB,TGZ
```

The package descriptor does not advertise a language, so omit `--language` when
invoking the package command.

V4L2 is always included. With a fresh CMake cache, the package defaults are:

| Build target | Operators |
| --- | --- |
| x86_64 | V4L2 |
| ARM64, including L4T R38.5 and SBSA without L4T | V4L2, SIPL |
| ARM64 with L4T R39 | V4L2, SIPL, Argus |

SIPL needs matching development headers. On R38.5, supply the SIPL source tree
as described in the [SIPL operator guide](../../operators/sipl_capture_op/README.md#igx-r385-host-prerequisite).
Argus needs its build headers and direct link libraries. Existing `OP_*` cache
values and explicitly enabled applications can also select operators; all
enabled operators installed in the `holoscan-camera` component enter the package.

For CLI packaging, pass `HOLOSCAN_CAMERA_PACKAGE_SIPL` and
`HOLOSCAN_CAMERA_PACKAGE_ARGUS` as container environment variables with
`--docker-opts`. Set each to `ON` or `OFF`; `AUTO` leaves the existing `OP_*`
cache value or platform default in effect. An environment choice seeds its
corresponding `OP_*` CMake cache option only when that option is unset. Use a
fresh build directory to change an earlier choice. Generic SBSA builders
without L4T development files can use:

```bash
./holoscan_camera package holoscan-camera --pkg-generator DEB \
    --docker-opts="-e HOLOSCAN_CAMERA_PACKAGE_SIPL=OFF -e HOLOSCAN_CAMERA_PACKAGE_ARGUS=OFF"
```

The installed CLI does not accept CMake options for its `package` command.
For direct CMake packaging, set the operator cache options instead. This example
selects V4L2 only on an ARM64 builder without camera development files:

```bash
cmake -S . -B build-package -G Ninja \
    -Dholoscan_ROOT="$HOLOSCAN_SDK_ROOT" \
    -DPKG_holoscan_camera=ON \
    -DOP_sipl_capture_op=OFF \
    -DOP_argus_capture_op=OFF
cmake --build build-package
cpack --config build-package/pkg/CPackConfig-holoscan-camera.cmake -G DEB
```

The defaults apply only when the corresponding `OP_*` cache value is not yet
defined. R39 selection includes Argus on Jetson Thor, although Argus runtime
qualification is limited to Orin.
L4T R38.5 package builds need matching SIPL headers. `ON` requires an ARM64
target and suitable development files.

The package carries the selected operator libraries, headers, and CMake package only.
Example applications install to the separate `holoscan-camera-examples`
component, which the package does not include. Applications follow their
existing `APP_<name>` CMake options, which default off when
`HOLOSCAN_CAMERA_BUILD_ALL=OFF`.
An enabled application also enables its required operator.

## metadata.json

`metadata.json` registers this package with the holohub CLI. Two fields matter:

- **`package` key** — marks this directory as a HoloHub *package* project. CLI 5
  scans the module's component directories, including `pkg/`, which makes it
  appear under the `PACKAGES` section of `./holoscan_camera list`.
- **`package.dockerfile`** — declares a Dockerfile path (relative to the module
  root) for this package-project record. When packaging this generated module
  by name, `./holoscan_camera package` instead selects the root `module` record and its
  `module.dockerfile`.

## Nested SDK builds

When nested inside the Holoscan SDK, the module installs as component
`holoscan-camera`. Its libraries, headers, executable, and CMake package files
are installed into the parent SDK layout, with the package config under
`<libdir>/cmake/holoscan-camera` and the exported targets under
`<libdir>/cmake/holoscan` as selected by GNUInstallDirs. Set
`HOLOSCAN_CAMERA_BUILD_DEB=ON` to opt into producing the Debian package from a
nested build.
