// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <v4l2_capture_op/v4l2_capture_op.hpp>

int main() {
  const holoscan::camera::V4l2CaptureOp op;
  return op.width() == 640 && op.height() == 480 ? 0 : 1;
}
