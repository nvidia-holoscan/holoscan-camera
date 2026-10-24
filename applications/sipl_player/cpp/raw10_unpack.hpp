// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// GPU unpacking of SIPLCaptureOp's RAW10 frames for sipl_player's --raw path.

#pragma once

#include <cuda_runtime_api.h>

#include <cstddef>
#include <cstdint>

namespace sipl_player {

// Unpacks one RAW10 frame in NvSci's X2Rc10Rb10Ra10 layout -- three 10-bit samples per
// little-endian 32-bit word, in bits [9:0], [19:10] and [29:20] -- into one 16-bit sample per
// pixel, shifted to the top of the 16-bit range. The output rows are `width` samples with no
// padding. `src_pitch` is the source row stride in bytes and must be a multiple of 4. Runs
// asynchronously on `stream`.
cudaError_t unpack_raw10(const void* src, std::size_t src_pitch, std::uint16_t* dst,
                         std::uint32_t width, std::uint32_t height, cudaStream_t stream);

}  // namespace sipl_player
