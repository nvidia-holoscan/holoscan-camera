// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "raw10_unpack.hpp"  // NOLINT(build/include_subdir)

namespace sipl_player {

namespace {

__global__ void unpack_raw10_kernel(const std::uint32_t* src, std::size_t src_pitch_words,
                                    std::uint16_t* dst, std::uint32_t width,
                                    std::uint32_t height) {
  const std::uint32_t x = blockIdx.x * blockDim.x + threadIdx.x;
  const std::uint32_t y = blockIdx.y * blockDim.y + threadIdx.y;
  if (x >= width || y >= height) {
    return;
  }
  const std::uint32_t word = src[y * src_pitch_words + x / 3U];
  const std::uint32_t sample = (word >> ((x % 3U) * 10U)) & 0x3FFU;
  dst[static_cast<std::size_t>(y) * width + x] = static_cast<std::uint16_t>(sample << 6U);
}

}  // namespace

cudaError_t unpack_raw10(const void* src, std::size_t src_pitch, std::uint16_t* dst,
                         std::uint32_t width, std::uint32_t height, cudaStream_t stream) {
  if (width == 0U || height == 0U) {
    return cudaSuccess;
  }
  const dim3 block(32, 8);
  const dim3 grid((width + block.x - 1U) / block.x, (height + block.y - 1U) / block.y);
  unpack_raw10_kernel<<<grid, block, 0, stream>>>(static_cast<const std::uint32_t*>(src),
                                                  src_pitch / sizeof(std::uint32_t), dst, width,
                                                  height);
  return cudaGetLastError();
}

}  // namespace sipl_player
