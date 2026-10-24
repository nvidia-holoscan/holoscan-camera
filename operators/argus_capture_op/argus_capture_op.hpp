// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
#pragma once

// clang-format off
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/parameter_schema.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/sensor_io/image_metadata.hpp>
#include <holoscan/sensor_io/sensor_schema_package.hpp>

#include "argus_capture_op/argus_frame_metadata_schema_traits.hpp"
// clang-format on

namespace holoscan::camera {

enum class ArgusPixelFormat : std::uint8_t { kNv12, kI420 };
enum class ArgusDropPolicy : std::uint8_t { kDropOldest, kDropNewest };

/// Configuration is fixed before setup(), including the tensor's geometry and placement.
/// Camera and mode indices are those reported by libargus, not /dev/videoN indices.
struct ArgusCaptureConfig {
  std::uint32_t camera_index{0};
  std::uint32_t sensor_mode{0};
  std::uint32_t width{1920};
  std::uint32_t height{1080};
  double fps{30.0};
  ArgusPixelFormat pixel_format{ArgusPixelFormat::kNv12};
  std::uint32_t buffer_count{6};
  ArgusDropPolicy drop_policy{ArgusDropPolicy::kDropOldest};
  std::uint32_t timeout_ms{2000};
  std::int32_t cuda_device{0};
  std::string frame_id{"camera_optical_frame"};
  /// Normal capture-to-GPU operation uses kCudaDevice. Host placements copy explicitly.
  holoscan::MemoryKind memory_kind{holoscan::MemoryKind::kCudaDevice};
  /// Optional, camera-calibrated correction: integration_start = VI_SOF + offset.
  /// Leave unset unless the sensor's timing establishes this relationship. Argus's generic
  /// first-data timestamp is always carried in metadata, but is not an integration timestamp.
  std::optional<std::int64_t> integration_start_offset_ns;
};

// Describe the native constructor configuration without duplicating its defaults.
// Constructor factories retain these values for graph embedding and compilation.
// cpplint parses the enum initializer inside this schema macro as a namespace body.
HOLOSCAN_PARAM_SCHEMA(
    ArgusCaptureConfig, param_schema("holoscan.camera.ArgusCaptureOp.Constructor", 1)
        .description("Capture NV12/I420 images and frame metadata on Jetson AGX Orin. "
                     "Device output requires an explicit GPU binding."),
    field<&ArgusCaptureConfig::camera_index>("camera_index")
        .description("Camera index in libargus enumeration, not a /dev/videoN index."),
    field<&ArgusCaptureConfig::sensor_mode>("sensor_mode")
        .description("Sensor mode index in libargus enumeration."),
    field<&ArgusCaptureConfig::width>("width")
        .range(2U, 16384U)
        .description("Even output width in pixels."),
    field<&ArgusCaptureConfig::height>("height")
        .range(2U, 16384U)
        .description("Even output height in pixels."),
    field<&ArgusCaptureConfig::fps>("fps")
        .range(0.1, 1000.0)
        .description("Requested frames per second."),
    field<&ArgusCaptureConfig::pixel_format>("pixel_format")
        .enum_values({param_enum_value("nv12", ArgusPixelFormat::kNv12),
                      // NOLINTNEXTLINE(whitespace/indent_namespace)
                      param_enum_value("i420", ArgusPixelFormat::kI420)})
        .description("Packed NV12 or I420 output layout."),
    field<&ArgusCaptureConfig::buffer_count>("buffer_count")
        .range(3U, 64U)
        .description("Number of native Argus capture buffers."),
    field<&ArgusCaptureConfig::drop_policy>("drop_policy")
        .enum_values({param_enum_value("drop_oldest", ArgusDropPolicy::kDropOldest),
                      // NOLINTNEXTLINE(whitespace/indent_namespace)
                      param_enum_value("drop_newest", ArgusDropPolicy::kDropNewest)})
        .description("Queue overflow policy."),
    field<&ArgusCaptureConfig::timeout_ms>("timeout_ms")
        .range(100U, 60000U)
        .description("No-frame deadline in milliseconds; must also cover one frame period."),
    field<&ArgusCaptureConfig::cuda_device>("cuda_device")
        .range(0, 0)
        .description("Jetson integrated GPU ordinal; only zero is supported."),
    field<&ArgusCaptureConfig::frame_id>("frame_id")
        .description("Image coordinate frame name, containing 1 to 256 bytes."),
    field<&ArgusCaptureConfig::memory_kind>("memory_kind")
        .enum_values({param_enum_value("host", MemoryKind::kHost),
                      param_enum_value("pinned", MemoryKind::kPinnedHost),
                      // NOLINTNEXTLINE(whitespace/indent_namespace)
                      param_enum_value("device", MemoryKind::kCudaDevice)})
        .description("Output tensor placement; device requires an explicit GPU binding."),
    field<&ArgusCaptureConfig::integration_start_offset_ns>("integration_start_offset_ns")
        .description("Optional calibrated integration-start offset from VI SOF, in nanoseconds."));

/// Jetson libargus source with bounded native buffers and descriptor-backed image output.
///
/// Owns one capture session. The worker posts OnNotified readiness; compute() copies the acquired
/// image into an HSDK pool and returns the native buffer before publishing. GPU placement requires
/// bind_tensor_output_device({.operator_path="camera", .output_port="frame", .device=DeviceId{0}}).
/// frame and metadata carry the same device sequence; publication on two ports is not atomic.
class ArgusCaptureOp final : public holoscan::Operator<> {
 public:
  explicit ArgusCaptureOp(ArgusCaptureConfig config = {});
  ~ArgusCaptureOp() override;
  ArgusCaptureOp(const ArgusCaptureOp&) = delete;
  ArgusCaptureOp& operator=(const ArgusCaptureOp&) = delete;

  void setup(holoscan::OperatorSpec& spec) override;
  [[nodiscard]] holoscan::Contract contract() const override;
  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext& context) override;

  holoscan::LifecycleStatus on_configure(holoscan::LifecycleContext&) noexcept;
  holoscan::LifecycleStatus on_allocate(holoscan::LifecycleContext&) noexcept;
  holoscan::LifecycleStatus on_arm(holoscan::LifecycleContext&) noexcept;
  holoscan::LifecycleStatus on_start(holoscan::LifecycleContext&) noexcept;
  holoscan::LifecycleStatus on_stop(holoscan::LifecycleContext&) noexcept;
  holoscan::LifecycleStatus on_release(holoscan::LifecycleContext&) noexcept;

  [[nodiscard]] const ArgusCaptureConfig& config() const noexcept { return config_; }
  [[nodiscard]] std::size_t frame_bytes() const noexcept { return frame_bytes_; }

  holoscan::Output<holoscan::schema::ImageT> frame;
  holoscan::Output<ArgusFrameMetadataT> metadata;

 private:
  struct Impl;
  ArgusCaptureConfig config_;
  std::size_t frame_bytes_;
  std::unique_ptr<Impl> impl_;
  holoscan::NotificationSource frame_ready_;
};

}  // namespace holoscan::camera
