# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Camera operators for Holoscan SDK 5 graphs.

Optional backends load only when their public API is requested.
"""

from importlib import import_module as _import_module

from . import operators as operators

_SIPL_TYPES = {"BayerFormat", "CameraInfo", "PixelFormat", "SIPLCaptureService"}
__all__ = ["operators"]
if "SIPLCaptureOp" in operators.__all__:
    __all__ += sorted(_SIPL_TYPES)
if any(name in operators.__all__ for name in ("SIPLCaptureOp", "ArgusCaptureOp")):
    __all__.append("schema")


def __getattr__(name: str):
    if name in _SIPL_TYPES and "SIPLCaptureOp" in operators.__all__:
        value = getattr(_import_module("._sipl", __name__), name)
    elif name == "schema" and name in __all__:
        value = _import_module(".schema", __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
