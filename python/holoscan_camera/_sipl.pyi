# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SIPL service types; runtime implementation requires the matching BSP."""

from enum import Enum

class PixelFormat(Enum):
    RAW_10 = 1
    RAW_12 = 2

class BayerFormat(Enum):
    BGGR = 0
    RGGB = 1
    GBRG = 2
    GRBG = 3

class CameraInfo:
    output_name: str
    offset: int
    embedded_top_lines: int
    embedded_bottom_lines: int
    width: int
    height: int
    bytes_per_line: int
    pixel_format: PixelFormat
    bayer_format: BayerFormat
    def __init__(self) -> None: ...

class SIPLCaptureService:
    def __init__(
        self,
        camera_config: str = "",
        json_config: str = "",
        raw_output: bool = False,
        capture_queue_depth: int = 4,
        nito_base_path: str = "/var/nvidia/nvcam/settings/sipl",
        timeout_us: int = 3_000_000,
        cuda_device: int = 0,
    ) -> None: ...
    def __holoscan_constructor_handle__(self, type_name: str) -> object: ...
    @staticmethod
    def list_available_configs(json_config: str = "") -> None: ...
    def get_camera_info(self) -> list[CameraInfo]: ...
    def camera_count(self) -> int: ...
