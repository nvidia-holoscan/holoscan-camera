# Developer Guide - Holoscan Camera

This guide covers the C++ SDK 5.x layout, build system, and CI workflow for
developing and distributing this Holoscan Module.

## Module Layout

```text
holoscan-camera/
├── holoscan_camera                 # CLI wrapper
├── Dockerfile                      # Development container image
├── CMakeLists.txt                  # Root CMake orchestration
├── cmake/container.ctest           # Project-local CTest driver for ./holoscan_camera test
├── tools/                          # Public development and validation helpers
├── metadata.json                   # Module metadata
├── pyproject.toml                  # Holoscan CLI project defaults
├── requirements-cli.txt            # Shared host/container CLI version pin
├── operators/v4l2_capture_op/      # C++ V4L2 capture operator and its unit tests
├── applications/holoscan_camera_v4l2/cpp/
└── pkg/holoscan-camera/            # Debian package metadata
```

Operator tests live beside the operator they cover, under
`operators/<op>/tests/`, and are declared while `operators/` is processed.

## Holoscan SDK baseline

Choose the SDK source baseline described in [SDK setup](README.md#holoscan-sdk-50-setup).
Build and install that checkout before selecting it for Camera development.
Enter the SDK source directory containing `run`:

```bash
cd <path/to/holoscan-sdk-source>
./run build \
    --build-python false \
    --build-benchmarks false
export HOLOSCAN_SDK_ROOT="$(pwd)/$(./run get_install_dir)"
cd -
```

CLI 5 selects the SDK from `--local-sdk-root`, `HOLOSCAN_SDK_ROOT`, nearby
SDK installations, then the container's SDK. The wrapper also accepts
`HOLOSCAN_SDK_INSTALL_DIR` as a legacy alias for `HOLOSCAN_SDK_ROOT`.
Build and test commands pass the selected SDK installation to CMake as
`holoscan_ROOT`.

The wrapper accepts an explicit base image through `--base-img` or
`HOLOSCAN_CLI_BASE_IMAGE`. Select an image compatible with your SDK installation.


### Public SDK container

Public SDK containers are published in the
[Holoscan NGC catalog](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara-holoscan/containers/holoscan)
at `nvcr.io/nvidia/clara-holoscan/holoscan`.
<!-- module-docs:sdk-ga-image -->
SDK container image reference:
`nvcr.io/nvidia/clara-holoscan/holoscan:v5.0.0-cuda13`.
<!-- /module-docs:sdk-ga-image -->
Verify that the selected tag is published and supports your platform in the
catalog, then select it with `--base-img` or `HOLOSCAN_CLI_BASE_IMAGE`.
If a compatible image is unavailable, use the
[source-build setup](README.md#using-holoscan-sdk-built-from-source).

## Wrapper Commands

| Command | What it does |
| --- | --- |
| `./holoscan_camera run-container` | Build and start the development container |
| `./holoscan_camera build holoscan_camera_v4l2 --language cpp` | Build the C++ validation application |
| `./holoscan_camera run holoscan_camera_v4l2 --language cpp` | Build and run the C++ validation application |
| `./holoscan_camera test holoscan_camera_v4l2 --language cpp` | Run CTest via `cmake/container.ctest` |
| `./holoscan_camera package holoscan-camera --pkg-generator DEB` | Build the Debian package |
| `./holoscan_camera package holoscan-camera --pkg-generator=WHEEL` | Build the Python wheel |

[`requirements-cli.txt`](requirements-cli.txt) owns the CLI pin and package index.
Edit this file instead of setting `HOLOSCAN_CLI_PINNED_VERSION`.
The wrapper runs `pip install -r` on the host; containers use the image's install.
After changing the pin, run `./holoscan_camera build-container` to rebuild it.
Use `HOLOSCAN_CLI_INSTALL_ARGS` for extra pip options or `HOLOSCAN_CLI_SOURCE`
for a local CLI checkout.

CLI 5 requires Python 3.11 or newer. The wrapper runs it with
`HOLOSCAN_CLI_PYTHON_BIN`, an active virtual environment, or its own venv
(`HOLOSCAN_CLI_VENV`, default `~/.local/share/holoscan-cli/venv`, created with
`python3`); containers use the image's `python3`. It stops with a fix when the
selected interpreter is older, including a wrapper venv created for an earlier CLI.

[`pyproject.toml`](pyproject.toml) configures project naming, CUDA, CTest, and
local SDK build-image names. The wrapper selects its configured default unless
`HOLOSCAN_CLI_BASE_IMAGE` or a CLI option overrides it.
It also forwards the SIPL hardware-test variables into containers when they are set.
CLI options override environment variables, which override these defaults.
CLI 5 discovers the module and its paths from `metadata.json`.

Direct CLI usage shares these settings, including local SDK selection:

```bash
python -m pip install -r requirements-cli.txt
holoscan list
holoscan build holoscan_camera_v4l2 --language cpp --dryrun --verbose
```

The CLI passes `--language` to CMake as `HOLOHUB_BUILD_CPP` and
`HOLOHUB_BUILD_PYTHON`. The top-level `CMakeLists.txt` maps them onto
`HOLOSCAN_CAMERA_BUILD_CPP` and `HOLOSCAN_CAMERA_BUILD_PYTHON`, so
`--language python` skips the C++ sample applications. Operators are built for
either language. An explicit `-DHOLOSCAN_CAMERA_BUILD_<LANGUAGE>` overrides the
CLI selection.

## Building Without The Wrapper

Installed consumers can link all enabled Camera operators through the module target:

```cmake
find_package(holoscan-camera REQUIRED)
target_link_libraries(my_pipeline PRIVATE holoscan::camera)
```

The same `holoscan::camera` alias is available when building from source. Individual
operator targets remain available; disabled operators are not linked by the aggregate.
When adding an operator, register its public target with `holoscan_camera` inside its
gated operator directory and install it in `holoscan_camera_targets`.

```bash
cmake -S . -B build -G Ninja \
    -Dholoscan_ROOT="$HOLOSCAN_SDK_ROOT" \
    -DHOLOSCAN_CAMERA_BUILD_ALL=ON \
    -DHOLOSCAN_CAMERA_BUILD_TESTING=ON
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure -LE gpu
```

The project uses C++20 and requires CMake 4.0 with a compatible Holoscan SDK
5.0 installation containing `holoscan::sensor_io`. See
[SDK installation troubleshooting](README.md#sdk-installation-troubleshooting)
if CMake rejects the selected installation.

Tests carry the labels `unit` for the operator's gtest suite, `plan` for the
application's `--validate` graph-compilation checks, and `gpu` for the subset of
those that need a visible CUDA device. `-LE gpu` is the exclusion for a host
without one.

With `PKG_holoscan_camera=ON`, `camera.installed_consumer` installs the Camera
components into a fresh prefix, checks the enabled operator exports, and builds and
runs a consumer linked only to `holoscan::camera`. Run it with
`ctest --test-dir build --output-on-failure -L package`.

Operator libraries are shared by default and carry the module `VERSION` and
`SOVERSION`; configure with `-DBUILD_SHARED_LIBS=OFF` only when a static developer
build is explicitly required.

## SDK 5.x API Shape

`V4l2CaptureOp` follows the typed operator pattern from the 5.x samples:

- `final : public holoscan::Operator<>`
- typed port member `holoscan::Output<holoscan::schema::ImageT> frame`
- `setup(holoscan::OperatorSpec&)` declares the port's tensor contract with
  `produces_tensor`, and registers one lifecycle hook per stage the device owns
- `contract()` returns an explicit `holoscan::Contract`, triggered by the
  reader thread's notification rather than by a clock
- `compute(holoscan::ExecutionContext&)` returns `holoscan::expected<void, holoscan::Error>`

The published payload is a `holoscan::schema::ImageT` carrying a packed YUYV
frame, not a bare tensor, so a consumer reads the geometry, encoding, frame
identifier, and acquisition instant from the sample. Frame placement is a
constructor parameter defaulting to `holoscan::MemoryKind::kHost`; see
[README.md](README.md) for the accepted values and for the explicit device
binding `kCudaDevice` requires.

The application uses `holoscan::Graph`, `graph.op<T>()`, and
`holoscan::compile`, and binds tensor output device placement only when the
requested placement is device-resident.

## Packaging

Build the Debian package and the raw `/usr`-layout CPack TGZ through the wrapper:

```bash
./holoscan_camera package holoscan-camera --pkg-generator DEB,TGZ
```

The Debian package installs below `/usr`; `/opt/nvidia/holoscan` is not a
supported package prefix.

Build the Python wheel with `--pkg-generator=WHEEL`; see
[Wheel builds](python/README.md#wheel-builds).


Keep these metadata fields synchronized before publishing:

| Field | Purpose |
| --- | --- |
| `metadata.json:module.version` | Module and Debian package version |
| `metadata.json:module.binary_packages` | Published Debian package name |
| `pkg/holoscan-camera/CMakeLists.txt` | Debian package dependency metadata |

## Naming Conventions

| Context | Convention | Example |
| --- | --- | --- |
| C++ namespace | `snake_case` | `holoscan::camera` |
| Repository folder | `holoscan-<slug>` | `holoscan-camera` |
| Debian package | `holoscan-<slug>` | `holoscan-camera` |
| CMake option prefix | `UPPER_SNAKE` | `HOLOSCAN_CAMERA_BUILD_TESTING` |

## Keeping SDK documentation current

[`docs/sdk-baseline.json`](docs/sdk-baseline.json) owns the explicitly selected
public SDK source tag. [`docs/ga-container.json`](docs/ga-container.json) separately
records the planned public GA image; it is not an availability record. Update
these inputs only after reviewing compatibility and release scope, then run:

```bash
python3 tools/sync_doc_versions.py --write
python3 tools/sync_doc_versions.py --check
```

Review and stage the generated documentation diff. Pre-commit checks for drift
without editing files, including when only the version input changes. Marked
regions use `camera-docs` comments with matching named begin/end markers.
The helper updates only these regions in the README, this guide, and the optional
internal development guide. Release-note history, platform versions, and
unmarked compatibility examples retain their original values.

The SDK tag is a source reference, not proof of testing or acceptance. The helper
performs no remote version discovery and makes no compatibility decision.

