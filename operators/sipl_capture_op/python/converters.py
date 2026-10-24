# SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CuPy operators for the frame formats SIPLCaptureOp publishes, and the helpers they use.

Importing this module needs CuPy.

- ``Raw10UnpackOp``: RAW10 frames (NvSci's X2Rc10Rb10Ra10 packing, published as a ``CUSTOM``
  image) -> 16-bit Bayer images, as holoscan_vision's ``BayerDemosaicOp`` takes them.
- ``Nv12ToRgbOp``: the ISP's NV12 frames (BT.709, full range) -> RGB8 images.

Both take frames in CUDA device memory, SIPLCaptureOp's default ``memory_kind``: a frame in host
or pinned memory fails the run. They write their output into runtime-pool loans on the
activation's CUDA stream, and carry each frame's capture time, frame and trace over to the image
they produce. A frame without a capture time yields an image without one.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Iterator
from typing import Any, cast

import cupy as cp  # type: ignore[import-untyped]  # CuPy ships no type information
import holoscan as hs
import numpy.typing as npt
from holoscan.schema.image import ImageEncoding

__all__ = [
    "Nv12ToRgbOp",
    "Raw10UnpackOp",
    "compile_kernels",
    "cuda_activation",
    "derive_from",
    "writable_view",
]

_UINT8 = hs.tensor.DLDataType(1, 8, 1)
_UINT16 = hs.tensor.DLDataType(1, 16, 1)
_BLOCK = (32, 8, 1)
_CUDA_DEVICE_TYPES = (
    hs.tensor.DLDeviceType.DLCUDA,
    hs.tensor.DLDeviceType.DLCUDAMANAGED,
)

# NvSci's X2Rc10Rb10Ra10 packing holds three 10-bit samples per little-endian 32-bit word, in
# bits [9:0], [19:10] and [29:20]. Each thread writes one pixel as a 16-bit sample shifted to the
# top of the 16-bit range; the output rows have no padding.
_UNPACK_RAW10 = cp.RawKernel(
    r"""
extern "C" __global__ void unpack_raw10(const unsigned int* src,
                                        unsigned long long src_pitch_words,
                                        unsigned short* dst, unsigned int width,
                                        unsigned int height) {
  const unsigned int x = blockIdx.x * blockDim.x + threadIdx.x;
  const unsigned int y = blockIdx.y * blockDim.y + threadIdx.y;
  if (x >= width || y >= height) {
    return;
  }
  const unsigned int word = src[y * src_pitch_words + x / 3U];
  const unsigned int sample = (word >> ((x % 3U) * 10U)) & 0x3FFU;
  dst[static_cast<unsigned long long>(y) * width + x] =
      static_cast<unsigned short>(sample << 6U);
}
""",
    "unpack_raw10",
)

# One thread per pixel: BT.709 full range, which SIPL's ISP output is (SIPLCaptureService
# allocates it as NvSciColorStd_REC709_ER). NV12's chroma plane holds one interleaved (Cb, Cr)
# pair per 2x2 pixels.
_NV12_TO_RGB = cp.RawKernel(
    r"""
extern "C" __global__ void nv12_to_rgb(const unsigned char* src, unsigned long long y_offset,
                                       unsigned long long y_pitch, unsigned long long uv_offset,
                                       unsigned long long uv_pitch, unsigned char* dst,
                                       unsigned int width, unsigned int height) {
  const unsigned int x = blockIdx.x * blockDim.x + threadIdx.x;
  const unsigned int y = blockIdx.y * blockDim.y + threadIdx.y;
  if (x >= width || y >= height) {
    return;
  }
  const float luma = src[y_offset + y * y_pitch + x];
  const unsigned char* uv = src + uv_offset + (y / 2U) * uv_pitch + (x / 2U) * 2U;
  const float cb = uv[0] - 128.0f;
  const float cr = uv[1] - 128.0f;
  const float rgb[3] = {luma + 1.5748f * cr, luma - 0.1873f * cb - 0.4681f * cr,
                        luma + 1.8556f * cb};
  unsigned char* out = dst + (static_cast<unsigned long long>(y) * width + x) * 3U;
  for (int c = 0; c < 3; ++c) {
    out[c] = static_cast<unsigned char>(fminf(fmaxf(rgb[c] + 0.5f, 0.0f), 255.0f));
  }
}
""",
    "nv12_to_rgb",
)


def compile_kernels() -> None:
    """Compile the operators' CUDA kernels now, rather than in their first activation, where a
    cold CuPy kernel cache costs seconds."""
    for kernel in (_UNPACK_RAW10, _NV12_TO_RGB):
        kernel.compile()


def derive_from(metadata: hs.SampleMetadata) -> hs.EmitOptions:
    """Emit options that carry a received sample's capture time, frame, trace and flags over to
    a value computed from it, like the C++ ``holoscan::sensor_io::derive_from()``. Absent fields
    stay absent: a sample without a capture time yields options without one."""
    provenance = hs.sensor_io.ProvenanceAccumulator()
    provenance.observe(metadata)
    return provenance.emit_options(hs.sensor_io.CaptureTimePolicy.EARLIEST)


def writable_view(tensor: hs.Tensor, dtype: npt.DTypeLike) -> cp.ndarray:
    """A CuPy array over a CUDA output loan's tensor, to fill it on the activation's stream.

    The loan's tensor refuses CuPy's stream-ordering imports (``cupy.from_dlpack`` and
    ``cupy.asarray`` raise ``kNotSupported``); it is written on the stream it was allocated for,
    so this wraps its pointer. Use the array only inside the loan's ``with`` block.
    """
    memory = cp.cuda.UnownedMemory(
        tensor.data, tensor.nbytes, tensor, tensor.device.device_id
    )
    return cp.ndarray(tensor.shape, dtype, cp.cuda.MemoryPointer(memory, 0))


@contextlib.contextmanager
def cuda_activation(context: hs.ExecutionContext, tensor: hs.Tensor) -> Iterator[None]:
    """Makes ``tensor``'s device and the activation's CUDA stream CuPy's current ones."""
    # The SDK types the stream as an object; it is the activation's CUDA stream, a context manager
    # that makes itself CuPy's current stream.
    stream = cast(contextlib.AbstractContextManager[Any], context.stream())
    with cp.cuda.Device(tensor.device.device_id), stream:
        yield


def _require_cuda_frame(tensor: hs.Tensor, operator: str) -> None:
    # A Python operator cannot declare a memory kind for an Image input (expects_tensor() takes
    # only Tensor inputs), so graph compilation does not catch a host frame; say what to change
    # rather than let CuPy's import fail.
    if tensor.device.device_type not in _CUDA_DEVICE_TYPES:
        raise ValueError(
            f"{operator} takes frames in CUDA device memory, not "
            f"{tensor.device.device_type.name}: create SIPLCaptureOp with "
            'memory_kind="device", its default'
        )


def _relabeled(image: hs.schema.Image, **changes: Any) -> hs.schema.Image:
    # Image is a dataclass at run time, which its stub does not declare.
    return cast(hs.schema.Image, dataclasses.replace(cast(Any, image), **changes))


def _byte_span_parameter(parameter: hs.Param[int]) -> hs.Param[object]:
    # parameter_byte_span() is typed for any Param; a Param[int] is one at run time.
    return cast("hs.Param[object]", parameter)


def _grid(width: int, height: int) -> tuple[int, int, int]:
    return (
        (width + _BLOCK[0] - 1) // _BLOCK[0],
        (height + _BLOCK[1] - 1) // _BLOCK[1],
        1,
    )


def _image_output_spec(dtype, rank: int) -> hs.tensor.OutputSpec:
    return hs.tensor.OutputSpec(
        storage="runtime_pool",
        memory_kind=hs.tensor.MemoryKind.CUDA_DEVICE,
        dtype=dtype,
        rank=rank,
        strides=hs.tensor.TensorStridePolicy.CONTIGUOUS_ONLY,
    )


class Raw10UnpackOp(hs.Operator):
    """SIPLCaptureOp's RAW10 frames -> 16-bit Bayer images for ``BayerDemosaicOp``.

    SIPLCaptureOp publishes RAW10 as a ``CUSTOM`` image: NvSci's packing has no Bayer encoding,
    and the Bayer phase travels separately, in the camera's ``CameraInfo``. This unpacks each frame
    into one 16-bit sample per pixel (the 10 bits at the top) and labels it with the phase. It
    takes frames in CUDA device memory (SIPLCaptureOp's default ``memory_kind="device"``).

    Parameters:
        max_output_bytes: Bytes of one unpacked frame (width x height x 2); sizes the output
            pool.
        bayer_encoding: The camera's Bayer phase, the name of an ``ImageEncoding.BAYER_*`` value.
    """

    input: hs.Input = hs.Input("input", hs.schema.Image)
    output: hs.Output = hs.Output("output", hs.schema.Image)

    max_output_bytes: hs.Param[int] = hs.Param(1, recompile_required=True)
    bayer_encoding: hs.Param[str] = hs.Param("BAYER_RGGB")

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.input, queue_depth=1)
        spec.output(self.output, max_emits_per_compute=1).produces_tensor(
            _image_output_spec(_UINT16, 3),
            hs.tensor.parameter_byte_span(
                _byte_span_parameter(type(self).max_output_bytes)
            ),
            field="data",
        )

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context: hs.ExecutionContext) -> None:
        sample = self.input.receive()
        image = cast(hs.schema.Image, sample.data)
        if image.encoding != ImageEncoding.CUSTOM or image.data is None:
            raise ValueError("Raw10UnpackOp expects SIPLCaptureOp's RAW10 frames")
        _require_cuda_frame(image.data, "Raw10UnpackOp")
        width, height = image.width, image.height
        if width <= 0 or height <= 0:
            raise ValueError(f"Raw10UnpackOp: the frame size {width}x{height} is empty")
        if width * height * 2 > self.max_output_bytes:
            raise ValueError(
                "Raw10UnpackOp: the RAW10 frame is larger than max_output_bytes"
            )

        # The frame's own descriptor, relabeled: same header, dimensions and timing.
        unpacked = _relabeled(
            image,
            data=None,
            encoding=ImageEncoding[self.bayer_encoding],
            significant_bits=10,
            plane_layouts=[],
        )
        options = derive_from(sample.metadata)
        try:
            loan = self.output.allocate_tensors(
                unpacked,
                {
                    "data": hs.tensor.LoanRequest(
                        shape=(height, width, 1), dtype=_UINT16
                    )
                },
                options=options,
            )
        except hs.errors.ResourceExhaustedError:
            return  # every buffer is still in use downstream: drop this frame

        # The loan is written, and the frame read, on the activation's CUDA stream.
        with cuda_activation(context, image.data), loan:
            packed = cp.from_dlpack(image.data)
            # SIPLCaptureOp publishes the active rows back to back: pitch x height bytes.
            pitch = packed.nbytes // height
            if (
                packed.nbytes % height != 0
                or pitch % 4 != 0
                or pitch < (width + 2) // 3 * 4
            ):
                raise ValueError(
                    "Raw10UnpackOp: the RAW10 row pitch does not match the width"
                )
            words = packed.reshape(-1).view(cp.uint32)
            output = writable_view(loan.tensors["data"], cp.uint16)
            _UNPACK_RAW10(
                _grid(width, height),
                _BLOCK,
                (
                    words,
                    cp.uint64(pitch // 4),
                    output,
                    cp.uint32(width),
                    cp.uint32(height),
                ),
            )


class Nv12ToRgbOp(hs.Operator):
    """SIPLCaptureOp's NV12 frames -> RGB8 images.

    SIPL's ISP output is BT.709, full range (SIPLCaptureService allocates it as
    ``NvSciColorStd_REC709_ER``), with the planes the frame's ``plane_layouts`` describe. It
    takes frames in CUDA device memory (SIPLCaptureOp's default ``memory_kind="device"``).

    Parameters:
        max_output_bytes: Bytes of one RGB frame (width x height x 3); sizes the output pool.
    """

    input: hs.Input = hs.Input("input", hs.schema.Image)
    output: hs.Output = hs.Output("output", hs.schema.Image)

    max_output_bytes: hs.Param[int] = hs.Param(1, recompile_required=True)

    def setup(self, spec: hs.OperatorSpec) -> None:
        spec.input(self.input, queue_depth=1)
        spec.output(self.output, max_emits_per_compute=1).produces_tensor(
            _image_output_spec(_UINT8, 3),
            hs.tensor.parameter_byte_span(
                _byte_span_parameter(type(self).max_output_bytes)
            ),
            field="data",
        )

    def contract(self) -> hs.Contract:
        return hs.Contract().trigger(hs.OnEach(self.input))

    def compute(self, context: hs.ExecutionContext) -> None:
        sample = self.input.receive()
        image = cast(hs.schema.Image, sample.data)
        if (
            image.encoding != ImageEncoding.NV12
            or image.data is None
            or len(image.plane_layouts) != 2
        ):
            raise ValueError("Nv12ToRgbOp expects SIPLCaptureOp's NV12 frames")
        _require_cuda_frame(image.data, "Nv12ToRgbOp")
        width, height = image.width, image.height
        if width <= 0 or height <= 0:
            raise ValueError(f"Nv12ToRgbOp: the frame size {width}x{height} is empty")
        if width * height * 3 > self.max_output_bytes:
            raise ValueError("Nv12ToRgbOp: the frame is larger than max_output_bytes")
        luma, chroma = image.plane_layouts
        # A chroma row holds one (Cb, Cr) byte pair per two pixels.
        if (
            luma.row_stride_bytes < width
            or chroma.row_stride_bytes < (width + 1) // 2 * 2
        ):
            raise ValueError("Nv12ToRgbOp: the NV12 rows are narrower than the frame")

        # The frame's own descriptor, relabeled: same header, dimensions and timing.
        rgb = _relabeled(
            image,
            data=None,
            encoding=ImageEncoding.RGB8,
            plane_layouts=[],
            significant_bits=0,
        )
        options = derive_from(sample.metadata)
        try:
            loan = self.output.allocate_tensors(
                rgb,
                {"data": hs.tensor.LoanRequest(shape=(height, width, 3), dtype=_UINT8)},
                options=options,
            )
        except hs.errors.ResourceExhaustedError:
            return  # every buffer is still in use downstream: drop this frame

        # The loan is written, and the frame read, on the activation's CUDA stream.
        with cuda_activation(context, image.data), loan:
            nv12 = cp.from_dlpack(image.data)
            if (
                luma.offset_bytes + luma.row_stride_bytes * height > nv12.nbytes
                or chroma.offset_bytes + chroma.row_stride_bytes * ((height + 1) // 2)
                > nv12.nbytes
            ):
                raise ValueError("Nv12ToRgbOp: the NV12 planes do not fit the frame")
            output = writable_view(loan.tensors["data"], cp.uint8)
            _NV12_TO_RGB(
                _grid(width, height),
                _BLOCK,
                (
                    nv12.reshape(-1),
                    cp.uint64(luma.offset_bytes),
                    cp.uint64(luma.row_stride_bytes),
                    cp.uint64(chroma.offset_bytes),
                    cp.uint64(chroma.row_stride_bytes),
                    output,
                    cp.uint32(width),
                    cp.uint32(height),
                ),
            )
