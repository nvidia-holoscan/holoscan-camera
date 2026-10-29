# V4L2 capture application

The V4L2 reference application compiles a capture graph without opening a device
or streams from a real camera and reports capture timestamps, frame quality, and
latency. See the [V4L2 operator guide](../../operators/v4l2_capture_op/README.md) for its capture and
memory-placement contracts and the [repository setup guide](https://docs.nvidia.com/holoscan/sdk-user-guide/setup/sdk-installation)
for SDK setup.

The commands below use the C++ application. For Python graph validation,
capture, and Holoviz preview, see the [Python application guide](python/README.md).

## Run

Run these commands from the repository root after completing SDK setup.

```bash
# Build the graph and validate it without touching a device (default mode).
./holoscan_camera run holoscan_camera_v4l2 --language cpp

# Stream from a real device. Requires the device to be mapped into the container.
./holoscan_camera run holoscan_camera_v4l2 capture --language cpp \
    --docker-opts '--device /dev/video0'

# Run CTest through the module CTest driver.
./holoscan_camera test holoscan_camera_v4l2 --language cpp
```

The mode is a positional argument, and application flags must travel through `--run-args`
because the CLI rejects unrecognized arguments of its own. The `capture` mode already supplies
`--capture --frames 60`, so `--run-args` is only needed to override defaults:

```bash
./holoscan_camera run holoscan_camera_v4l2 capture --language cpp \
    --docker-opts '--device /dev/video2' \
    --run-args '--device /dev/video2 --frames 300 --timeout 30'
```

`--memory-kind {host|pinned|device}` selects the frame placement described under
[Frame placement](../../operators/v4l2_capture_op/README.md#frame-placement), applying it to the source *and* the reference sink so the two
port contracts agree. Because the placement is settled when the plan compiles, the default
`--validate` mode exercises it with no camera attached:

```bash
# Compiles the plan with a device placement and reports it; opens no device.
./holoscan_camera run holoscan_camera_v4l2 --language cpp \
    --run-args '--memory-kind device'
```
