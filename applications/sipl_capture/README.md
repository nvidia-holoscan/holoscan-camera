# sipl_capture

Captures frames and their metadata from every camera of an NvSIPL camera
configuration in a Python graph, through the
[SIPL Python bindings](../../operators/sipl_capture_op/python/README.md) of
[sipl_capture_op](../../operators/sipl_capture_op). It shows no video: for each
camera, it prints the frame size and device sequence and, optionally, each
frame's HSB and SIPL metadata. For live video, see
[sipl_player](../sipl_player/README.md).

## Run

```bash
./holoscan_camera run sipl_capture capture --language python --run-args \
  '--json-config applications/config/sipl/vb1940_dual.json --frames 300 --print-metadata'
```

The `validate` mode, the default, compiles the graph for one camera without
opening it. Set the camera MAC addresses in the JSON config to match your
connected cameras before running. The CLI launches the application from the
repository root, so a relative `--json-config` path resolves from that
directory. For container runs, the application metadata runs the container
privileged: NvSIPL reads `/proc/device-tree/model` when it loads the camera query
database, which Docker hides from unprivileged containers, and opening the
cameras needs device access they don't have.

Without the CLI, from the Camera repository root, with the SIPL Python
bindings built (see [Build](../../operators/sipl_capture_op/python/README.md#build)) and the matching SDK Python
package importable:

```bash
export PYTHONPATH="$PWD/build-sipl-python/python/lib${PYTHONPATH:+:$PYTHONPATH}"
python3.12 applications/sipl_capture/python/sipl_capture.py --validate
python3.12 applications/sipl_capture/python/sipl_capture.py --list-configs \
  --json-config applications/config/sipl/vb1940_dual.json
python3.12 applications/sipl_capture/python/sipl_capture.py \
  --json-config applications/config/sipl/vb1940_dual.json --frames 300 --print-metadata
```

## Options

Live capture opens and streams all of the configuration's cameras, feeds the
graph from all of them or the first `--cameras`, and stops the run when a camera
has delivered `--frames` frames. `--print-metadata` logs each frame's HSB and
SIPL metadata. `--raw` publishes the sensor's RAW frames instead of the ISP's
NV12, and `--memory-kind` places the frames in `device` (the default), `pinned`,
or `host` memory. Choose a configuration with `--camera-config`; the default is
the first one the SIPL database lists.

## Tests

With the SIPL Python bindings, `python-camera.sipl` validates the graph for
each memory kind without opening a camera, and runs the application's metadata
printer on synthetic records.
