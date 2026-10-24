# SIPL platform configs

Vendor JSON platform configs for the Leopard Imaging VB1940 Eagle camera,
shared across the SIPL apps (`--json-config` / `SIPL_JSON_CONFIG`) and the
SIPL operator's hardware tests. Ingested directly by the NvSIPL camera stack
(`SIPLCaptureService`'s `json_config` argument) — this project does not parse
or transform them. Each file adheres to the SIPL Query JSON schema; see the
[SIPL JSON Query Guide](https://docs.nvidia.com/jetson/archives/r39.2/DeveloperGuide/SD/CameraDevelopment/SIPLFramework/SIPL-for-L4T/SIPL-JSON-Query-Guide.html#coe-camera-development).

| File | Cameras | Source |
| --- | --- | --- |
| `vb1940_single.json` | One, independent | [Holoscan Sensor Bridge `vb1940_single.json`](https://github.com/nvidia-holoscan/holoscan-sensor-bridge/blob/4b192aee3fbf1cfa35a498c592c0f5d4081b4cdc/examples/sipl_config/vb1940_single.json) at `4b192aee` |
| `vb1940_dual.json` | Two, independent (not hardware-synced) | [Holoscan Sensor Bridge `vb1940_dual.json`](https://github.com/nvidia-holoscan/holoscan-sensor-bridge/blob/4b192aee3fbf1cfa35a498c592c0f5d4081b4cdc/examples/sipl_config/vb1940_dual.json) at `4b192aee` |
| `vb1940_stereo.json` | Two, hardware-synced (`isStereo`, `sensorGroup`, `sync_sensors`) | Derived here from `vb1940_dual.json` for [sipl_stereo_monitor](../../sipl_stereo_monitor) |

`vb1940_single.json` and `vb1940_dual.json` are byte-identical to the files in the
public [Holoscan Sensor Bridge examples](https://github.com/nvidia-holoscan/holoscan-sensor-bridge/tree/main/examples),
under `sipl_config/`, at verified commit
[`4b192aee3fbf1cfa35a498c592c0f5d4081b4cdc`](https://github.com/nvidia-holoscan/holoscan-sensor-bridge/tree/4b192aee3fbf1cfa35a498c592c0f5d4081b4cdc/examples/sipl_config).
The comparison covers the exact file bytes, including whitespace; the source
links above pin that snapshot rather than the moving `main` branch.

`vb1940_stereo.json` is derived locally from `vb1940_dual.json` and adds the
stereo-sync fields. The public `examples/sipl_config/` directory has no stereo
counterpart at that commit. Review any future upstream stereo configuration
before replacing the local variant.
