// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// sipl_player — shows live video from every camera of an NvSIPL camera configuration in a HoloViz
// window. Holoscan SDK 5 port of Holoscan Sensor Bridge's examples/sipl_player.cpp.
//
// By default SIPL's ISP processes the frames and SIPLCaptureOp publishes NV12, which HoloViz
// converts and draws:
//
//   SIPLCaptureOp (NV12) -> HolovizOp
//
// With --raw, SIPL delivers the sensor's RAW10 Bayer data instead, and the app unpacks and
// demosaics it on the GPU:
//
//   SIPLCaptureOp (RAW10) -> Raw10UnpackOp -> BayerDemosaicOp -> HolovizOp
//
// The HSB version also ran HSB's ImageProcessorOp (optical black and white balance) on the RAW
// path. This module does not depend on HSB, so --raw shows the sensor's uncorrected colors.
//
// All cameras share one SIPLCaptureService and are tiled left to right in one window; with
// --separate, each camera gets its own window instead. (HSB's --separate ran each camera as a
// separate application. HSDK5's HoloViz does not serialize its window-system calls across threads,
// so here all windows belong to one graph and are serviced from one lane, and closing any of them
// stops the player.)
//
// Usage:
//   sipl_player --json-config applications/config/sipl/vb1940_dual.json
//   sipl_player --list-configs

#include <pthread.h>
#include <signal.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <limits>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <holoscan/core/compile.hpp>
#include <holoscan/core/connection_options.hpp>
#include <holoscan/core/diagnostic.hpp>
#include <holoscan/core/errors.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/execution_plan.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/parameter_schema.hpp>
#include <holoscan/core/run.hpp>
#include <holoscan/core/run_session.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/core/tensor_output_loan.hpp>
#include <holoscan/logger/logger.hpp>
#include <holoscan/sensor_io/image_metadata.hpp>
#include <holoscan/sensor_io/provenance.hpp>
#include <holoscan/time/realtime_clock.hpp>
#include <holoscan/vision/bayer_demosaic_op.hpp>
#include <holoscan/visualization/holoviz_op.hpp>
#include <holoscan/visualization/sink_desc.hpp>

#include <NvSIPLISPStat.hpp>

#include <sipl_capture_op/sipl_capture_op.hpp>
#include <sipl_capture_op/sipl_capture_service.hpp>

#include "raw10_unpack.hpp"  // NOLINT(build/include_subdir)

namespace camera = holoscan::camera;
namespace viz = holoscan::visualization;

// ---------------------------------------------------------------------------
// Raw10UnpackOp: SIPLCaptureOp's RAW10 frames -> 16-bit Bayer for BayerDemosaicOp (--raw only).
// ---------------------------------------------------------------------------

struct Raw10UnpackParams {
  // Bytes of one unpacked frame (width x height x 2); sizes the output pool.
  std::uint64_t max_output_bytes{1U};
};

HOLOSCAN_PARAM_SCHEMA(
    Raw10UnpackParams,
    holoscan::param_schema("com.nvidia.holoscan_camera.sipl_player.Raw10UnpackParams", 1),
    holoscan::field<&Raw10UnpackParams::max_output_bytes>("max_output_bytes")
        .recompile_required()
        .description("Bytes of one unpacked frame; sizes the output pool."));

namespace {

constexpr DLDataType kUInt8{static_cast<std::uint8_t>(kDLUInt), 8, 1};
constexpr DLDataType kUInt16{static_cast<std::uint8_t>(kDLUInt), 16, 1};

// SIPLCaptureOp publishes RAW10 as ImageEncoding_CUSTOM: NvSci's X2Rc10Rb10Ra10 packing (three
// 10-bit samples per 32-bit word) has no BAYER_* encoding, and the Bayer phase travels separately
// in SIPLCaptureService::CameraInfo. This operator unpacks each frame into one 16-bit sample per
// pixel, shifted to the top of the 16-bit range, and labels it with the phase, which is the
// single-channel mosaic BayerDemosaicOp takes.
class Raw10UnpackOp final : public holoscan::Operator<Raw10UnpackParams> {
 public:
  explicit Raw10UnpackOp(holoscan::schema::ImageEncoding bayer_encoding)
      : bayer_encoding_(bayer_encoding) {}

  holoscan::Input<holoscan::schema::ImageT> input{"input"};
  holoscan::Output<holoscan::schema::ImageT> output{"output"};

  void setup(holoscan::OperatorSpec& spec) override {
    spec.input(input, "input")
        .queue_depth(1U)
        .tensor_field(holoscan::schema::ImageTensorFields::data)
        .expects_tensor(holoscan::TensorInputSpec{
            .representation = {.memory_kind = holoscan::MemoryKind::kCudaDevice,
                               .dtype = kUInt8},
        });
    spec.output(output, "output")
        .max_emits_per_compute(1U)
        .tensor_field(holoscan::schema::ImageTensorFields::data)
        .produces_tensor(
            holoscan::TensorOutputSpec{
                .representation = {.memory_kind = holoscan::MemoryKind::kCudaDevice,
                                   .dtype = kUInt16,
                                   .rank = 3U,
                                   .strides = holoscan::TensorStridePolicy::kContiguousOnly},
                .storage = holoscan::TensorOutputStorage::kRuntimePool,
            },
            holoscan::parameter_byte_span(
                holoscan::param_ref<&Raw10UnpackParams::max_output_bytes>()));
  }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract c;
    c.trigger(holoscan::OnEach{input});
    return c;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext& context) override {
    auto sample = input.receive();
    if (!sample) {
      return holoscan::make_unexpected(std::move(sample).error());
    }
    const holoscan::schema::ImageT& image = sample->data;
    if (image.encoding != holoscan::schema::ImageEncoding_CUSTOM || !image.data) {
      return invalid("expects SIPLCaptureOp's RAW10 frames (CUSTOM encoding)");
    }
    const auto width = static_cast<std::uint32_t>(std::max(image.width, 0));
    const auto height = static_cast<std::uint32_t>(std::max(image.height, 0));
    const std::size_t in_bytes = static_cast<std::size_t>(image.data->nbytes());
    if (width == 0U || height == 0U || in_bytes % height != 0U) {
      return invalid("RAW10 frame size does not match its dimensions");
    }
    // SIPLCaptureOp publishes the active rows back to back: pitch x height bytes.
    const std::size_t pitch = in_bytes / height;
    if (pitch % 4U != 0U || pitch < (width + 2U) / 3U * 4U) {
      return invalid("RAW10 row pitch is too small or not a multiple of 4 bytes");
    }
    if (static_cast<std::uint64_t>(width) * height * 2U > params().max_output_bytes) {
      return invalid("RAW10 frame is larger than max_output_bytes");
    }

    const std::array<std::int64_t, 3> shape{height, width, 1};
    auto loan =
        output.allocate_tensor(holoscan::TensorLoanRequest{.shape = shape, .dtype = kUInt16});
    if (!loan) {
      if (loan.error().code == holoscan::ErrorCode::kResourceExhausted) {
        return {};  // every slot is still on its way to the display: drop this frame
      }
      return holoscan::make_unexpected(std::move(loan).error());
    }
    auto writer = loan->write(context.cuda_stream());
    if (!writer) {
      return holoscan::make_unexpected(std::move(writer).error());
    }
    const cudaError_t launched =
        sipl_player::unpack_raw10(image.data->data(), pitch,
                                  static_cast<std::uint16_t*>(writer->data()), width, height,
                                  context.cuda_stream().get());
    if (launched != cudaSuccess) {
      return holoscan::make_unexpected(
          holoscan::Error{holoscan::ErrorCode::kFailure,
                          std::string("Raw10UnpackOp: ") + cudaGetErrorString(launched)});
    }
    auto committed = std::move(*writer).commit();
    if (!committed) {
      return holoscan::make_unexpected(std::move(committed).error());
    }

    // The frame's own descriptor, relabeled: same header, dimensions and timing.
    holoscan::schema::ImageT unpacked = image;
    unpacked.encoding = bayer_encoding_;
    unpacked.significant_bits = 10U;
    unpacked.plane_layouts.clear();
    return output.emit_tensor(std::move(*loan), unpacked,
                              holoscan::sensor_io::derive_from(sample->metadata));
  }

 private:
  static holoscan::unexpected<holoscan::Error> invalid(std::string_view message) {
    return holoscan::make_unexpected(holoscan::Error{holoscan::ErrorCode::kInvalidArgument,
                                                     "Raw10UnpackOp " + std::string(message)});
  }

  holoscan::schema::ImageEncoding bayer_encoding_;
};

// ---------------------------------------------------------------------------
// SIPLCountAndPrintOp: drains a camera's sensor_data port; --metadata and --frame-limit.
// ---------------------------------------------------------------------------

// --frame-limit for one session: it stops once every camera in it has delivered frame_limit
// frames.
struct FrameLimit {
  std::uint64_t frame_limit{0};  // 0 = no limit
  std::atomic<std::size_t> cameras_remaining{0};
};

struct SensorDataParams {
  std::string camera_name;
  bool print_metadata{false};
  std::shared_ptr<FrameLimit> frame_limit;
};

// SIPLCaptureOp publishes one SIPLFrameMetadata record per frame on sensor_data. This prints it
// with --metadata (the HSB record, the SIPL capture-start and end-of-frame times and, from the
// ISP, the first local average statistics window) and counts the camera's frames for --frame-limit.
class SIPLCountAndPrintOp final : public holoscan::Operator<SensorDataParams> {
 public:
  holoscan::Input<camera::SIPLFrameMetadataT> input{"input"};

  void setup(holoscan::OperatorSpec& spec) override { spec.input(input, "input").queue_depth(4U); }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract c;
    c.trigger(holoscan::OnEach{input});
    return c;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext& context) override {
    auto sample = input.receive();
    if (!sample) {
      return holoscan::make_unexpected(std::move(sample).error());
    }
    const auto& p = params();
    if (p.print_metadata) {
      print(p.camera_name, sample->data);
    }
    ++frames_;
    if (p.frame_limit && p.frame_limit->frame_limit != 0U &&
        frames_ == p.frame_limit->frame_limit &&
        p.frame_limit->cameras_remaining.fetch_sub(1U) == 1U) {
      context.request_stop();
    }
    return {};
  }

 private:
  void print(const std::string& camera_name, const camera::SIPLFrameMetadataT& m) {
    if (m.hsb_valid) {
      HOLOSCAN_LOG_INFO("[{}] frame={}, ts={}.{:09}, meta_ts={}.{:09}, crc=0x{:08x}, bytes={}",
                        camera_name, m.hsb_frame_number, m.hsb_timestamp_s, m.hsb_timestamp_ns,
                        m.hsb_metadata_s, m.hsb_metadata_ns, m.hsb_crc, m.hsb_bytes_written);
    } else {
      HOLOSCAN_LOG_INFO("[{}] (no HSB metadata)", camera_name);
    }
    HOLOSCAN_LOG_INFO("    SIPL Metadata: start time={}, end time={}", m.frame_capture_start_tsc,
                      m.frame_capture_end_tsc);
    // The ISP statistics (NV12 mode only) are a verbatim copy of nvsipl::IspStatsInfo.
    if (m.isp_stats_blob.size() == sizeof(nvsipl::IspStatsInfo)) {
      if (!isp_stats_) {
        isp_stats_ = std::make_unique<nvsipl::IspStatsInfo>();  // ~400 KB: not on the stack
      }
      std::memcpy(isp_stats_.get(), m.isp_stats_blob.data(), sizeof(nvsipl::IspStatsInfo));
      const auto& average = isp_stats_->ispStatsData.lacStatsData[0].data[0].average[0];
      HOLOSCAN_LOG_INFO("    LAC Averages (window 0): ({:.4f}, {:.4f}, {:.4f}, {:.4f})",
                        average[0], average[1], average[2], average[3]);
    }
  }

  std::uint64_t frames_{0};
  std::unique_ptr<nvsipl::IspStatsInfo> isp_stats_;
};

// ---------------------------------------------------------------------------
// DiscardImageOp: with --headless, drains HolovizOp's rendered frames.
// ---------------------------------------------------------------------------

class DiscardImageOp final : public holoscan::Operator<> {
 public:
  holoscan::Input<holoscan::schema::ImageT> input{"input"};

  void setup(holoscan::OperatorSpec& spec) override {
    (void)spec.input(input, "input").tensor_field(holoscan::schema::ImageTensorFields::data);
  }

  [[nodiscard]] holoscan::Contract contract() const override {
    holoscan::Contract c;
    c.trigger(holoscan::OnEach{input});
    return c;
  }

  [[nodiscard]] holoscan::expected<void, holoscan::Error> compute(
      holoscan::ExecutionContext&) override {
    auto sample = input.receive();
    if (!sample) {
      return holoscan::make_unexpected(std::move(sample).error());
    }
    return {};
  }
};

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

struct Options {
  std::string camera_config;
  std::string json_config;
  bool list_configs{false};
  bool raw{false};
  bool headless{false};
  bool fullscreen{false};
  bool separate{false};
  std::uint64_t frame_limit{0};
  bool print_metadata{false};
  std::int32_t cuda_device{0};
  bool validate{false};
  bool show_help{false};
};

void print_usage(std::ostream& out, std::string_view prog) {
  out << "Usage: " << prog << " [options]\n\n"
      << "Show live video from every camera of an NvSIPL camera configuration.\n\n"
      << "Options:\n"
      << "  --camera-config NAME   SIPL camera configuration name (default: the first one\n"
      << "                         found in the SIPL database or --json-config)\n"
      << "  --json-config PATH     Vendor JSON platform config\n"
      << "  --list-configs         List the available camera configurations and exit\n"
      << "  --raw                  Capture RAW10 and unpack and demosaic it on the GPU,\n"
      << "                         instead of showing SIPL's ISP output\n"
      << "  --separate             Show each camera in its own window\n"
      << "  --frame-limit N        Stop after N frames from every camera (default: 0, run\n"
      << "                         until the window closes or Ctrl+C)\n"
      << "  --metadata             Print each frame's metadata\n"
      << "  --headless             Render into a CUDA image instead of a window\n"
      << "  --fullscreen           Run in fullscreen mode\n"
      << "  --cuda-device N        CUDA device ordinal (default: 0); with a window, it must be\n"
      << "                         the GPU that drives the display\n"
      << "  --validate             Compile the graph for two placeholder 1920x1080 cameras and\n"
      << "                         exit, without opening a camera\n"
      << "  -h, --help             Show this help text\n";
}

std::string_view next_arg(int& i, int argc, char** argv, std::string_view opt) {
  if (i + 1 >= argc) {
    throw std::invalid_argument(std::string(opt) + " requires a value");
  }
  return argv[++i];
}

std::uint64_t parse_count(std::string_view value, std::string_view opt) {
  std::size_t used = 0;
  const std::string text(value);
  unsigned long long parsed = 0;  // NOLINT(runtime/int): std::stoull's own type
  try {
    parsed = std::stoull(text, &used);
  } catch (const std::exception&) {
    used = 0;
  }
  if (text.empty() || used != text.size() || text.front() == '-') {
    throw std::invalid_argument(std::string(opt) + " needs a non-negative integer, got '" + text +
                                "'");
  }
  return parsed;
}

Options parse_options(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    const std::string_view arg{argv[i]};
    if (arg == "-h" || arg == "--help") {
      o.show_help = true;
    } else if (arg == "--camera-config") {
      o.camera_config = next_arg(i, argc, argv, arg);
    } else if (arg == "--json-config") {
      o.json_config = next_arg(i, argc, argv, arg);
    } else if (arg == "--list-configs") {
      o.list_configs = true;
    } else if (arg == "--raw") {
      o.raw = true;
    } else if (arg == "--separate") {
      o.separate = true;
    } else if (arg == "--frame-limit") {
      o.frame_limit = parse_count(next_arg(i, argc, argv, arg), arg);
    } else if (arg == "--metadata") {
      o.print_metadata = true;
    } else if (arg == "--headless") {
      o.headless = true;
    } else if (arg == "--fullscreen") {
      o.fullscreen = true;
    } else if (arg == "--cuda-device") {
      const std::uint64_t device = parse_count(next_arg(i, argc, argv, arg), arg);
      if (device > static_cast<std::uint64_t>(std::numeric_limits<std::int32_t>::max())) {
        throw std::invalid_argument("--cuda-device is out of range: " + std::to_string(device));
      }
      o.cuda_device = static_cast<std::int32_t>(device);
    } else if (arg == "--validate") {
      o.validate = true;
    } else {
      throw std::invalid_argument("unknown option: " + std::string(arg));
    }
  }
  return o;
}

// ---------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------

using CameraInfo = camera::SIPLCaptureService::CameraInfo;
using BayerFormat = camera::SIPLCaptureService::BayerFormat;

holoscan::schema::ImageEncoding bayer_encoding(BayerFormat format) {
  switch (format) {
    case BayerFormat::kBggr:
      return holoscan::schema::ImageEncoding_BAYER_BGGR;
    case BayerFormat::kRggb:
      return holoscan::schema::ImageEncoding_BAYER_RGGB;
    case BayerFormat::kGbrg:
      return holoscan::schema::ImageEncoding_BAYER_GBRG;
    case BayerFormat::kGrbg:
      return holoscan::schema::ImageEncoding_BAYER_GRBG;
  }
  throw std::invalid_argument("unknown Bayer format");
}

holoscan::vision::BayerGridPosition bayer_grid_position(BayerFormat format) {
  switch (format) {
    case BayerFormat::kBggr:
      return holoscan::vision::BayerGridPosition::kBGGR;
    case BayerFormat::kRggb:
      return holoscan::vision::BayerGridPosition::kRGGB;
    case BayerFormat::kGbrg:
      return holoscan::vision::BayerGridPosition::kGBRG;
    case BayerFormat::kGrbg:
      return holoscan::vision::BayerGridPosition::kGRBG;
  }
  throw std::invalid_argument("unknown Bayer format");
}

// HolovizOp that, when it shows a window, declares that its callbacks must not run concurrently
// with another window's: Holoscan SDK 5's HoloViz does not serialize its window-system (GLFW) calls
// across threads. A shared serialization domain makes the partition planner give every window one
// serial owner; an authored partition cannot, since the windows are not connected to each other.
// The SDK's only per-operator hook for that is host_metadata(), hence the subclass. A headless
// HolovizOp renders into a CUDA image without a window system, so it declares no domain.
class DisplayOp final : public viz::HolovizOp {
 public:
  template <typename... Args>
  explicit DisplayOp(bool window, Args&&... args)
      : viz::HolovizOp(std::forward<Args>(args)...), window_(window) {}

  [[nodiscard]] holoscan::OperatorHostMetadata host_metadata() const noexcept override {
    if (!window_) {
      return {};
    }
    return {.serialization_domain = "sipl_player.holoviz_window"};
  }

 private:
  bool window_;
};

// One HolovizOp: the cameras it shows (indices into the service's camera list), tiled left to
// right at their native aspect ratio.
struct Display {
  std::string name;
  std::string title;
  std::vector<std::uint32_t> cameras;
};

// Builds and compiles the player's graph: every camera in `infos` (the service's camera list), in
// one window or, with --separate, each in its own.
holoscan::ExecutionPlan compile_player(holoscan::Graph& graph,  // NOLINT(runtime/references)
                                       const Options& opts,
                                       const std::shared_ptr<camera::SIPLCaptureService>& service,
                                       const std::vector<CameraInfo>& infos) {
  holoscan::CompileOptions compile_options;
  const auto bind_device = [&](const std::string& op, const std::string& port) {
    compile_options.deployment.bind_tensor_output_device(
        {.operator_path = op, .output_port = port,
         .device = holoscan::DeviceId{.value = opts.cuda_device}});
  };

  // Every edge from a camera is a freshest-frame mailbox: SIPLCaptureOp must never find a full
  // queue, and the display skips to the latest frame when it falls behind.
  const holoscan::ConnectionOptions mailbox{.queue_policy = holoscan::QueuePolicy::kDropOldest,
                                            .queue_depth = 1U};
  // A window renders each frame of its first camera as it arrives, with frames of the other
  // cameras captured no later than it: for cameras that capture together, usually the ones before.
  // Keep two of theirs, so that a frame captured a moment after the first camera's cannot push out
  // the one before it and leave the layer with nothing to show.
  const holoscan::ConnectionOptions side_layer{.queue_policy = holoscan::QueuePolicy::kDropOldest,
                                               .queue_depth = 2U};
  const holoscan::ConnectionOptions sensor_data_edge{
      .queue_policy = holoscan::QueuePolicy::kDropOldest, .queue_depth = 4U};

  std::vector<Display> displays;
  if (opts.separate) {
    for (std::uint32_t index = 0; index < infos.size(); ++index) {
      displays.push_back(Display{.name = "holoviz" + std::to_string(index),
                                 .title = infos[index].output_name,
                                 .cameras = {index}});
    }
  } else {
    if (infos.size() > viz::kMaxLayerPorts) {
      throw std::runtime_error("one window shows at most " +
                               std::to_string(viz::kMaxLayerPorts) + " cameras, the configuration has " +
                               std::to_string(infos.size()) + "; use --separate");
    }
    Display all{.name = "holoviz", .title = "SIPL Player", .cameras = {}};
    for (std::uint32_t index = 0; index < infos.size(); ++index) {
      all.cameras.push_back(index);
    }
    displays.push_back(std::move(all));
  }

  auto frame_limit = std::make_shared<FrameLimit>();
  frame_limit->frame_limit = opts.frame_limit;
  frame_limit->cameras_remaining = infos.size();

  for (const Display& display : displays) {
    // Window size: the tiled cameras at their native aspect ratio, scaled down to fit 1920x1080.
    std::uint64_t total_width = 0;
    std::uint32_t max_height = 0;
    for (const std::uint32_t index : display.cameras) {
      total_width += infos.at(index).width;
      max_height = std::max(max_height, infos.at(index).height);
    }
    if (total_width == 0U || max_height == 0U) {
      throw std::runtime_error("the camera configuration reports an empty frame size");
    }
    const double scale = std::min({1.0, 1920.0 / static_cast<double>(total_width),
                                   1080.0 / static_cast<double>(max_height)});
    const auto width = static_cast<std::uint32_t>(std::lround(total_width * scale));
    const auto height = static_cast<std::uint32_t>(std::lround(max_height * scale));

    viz::LayerStack layers;
    std::uint64_t left = 0;
    for (const std::uint32_t index : display.cameras) {
      const CameraInfo& info = infos.at(index);
      viz::ImageLayerDesc layer{
          .format = opts.raw ? viz::ImageFormat::kR16G16B16A16Unorm : viz::ImageFormat::kNV12,
          .max_width = info.width,
          .max_height = info.height,
      };
      if (!opts.raw) {
        // SIPLCaptureService allocates the ISP output as NvSciColorStd_REC709_ER: BT.709, full
        // range.
        layer.yuv_model = viz::YUVModelConversion::kBT709;
        layer.yuv_range = viz::YUVRange::kFull;
      }
      if (display.cameras.size() > 1U) {
        layer.view = viz::ViewTransform{
            .offset_x = static_cast<float>(left) / static_cast<float>(total_width),
            .offset_y = 0.F,
            .scale_x = static_cast<float>(info.width) / static_cast<float>(total_width),
            .scale_y = static_cast<float>(info.height) / static_cast<float>(max_height),
        };
      }
      left += info.width;
      layers.add_image_layer("camera" + std::to_string(index), layer);
    }

    viz::SinkDesc sink;
    if (opts.headless) {
      sink = viz::CudaSinkDesc{.width = width, .height = height};
      bind_device(display.name, "output");
    } else {
      sink = viz::WindowSinkDesc{
          .title = display.title,
          // Fullscreen keeps the monitor's current mode; a size would switch it to the closest
          // one.
          .width = opts.fullscreen ? 0U : width,
          .height = opts.fullscreen ? 0U : height,
          .fullscreen = opts.fullscreen,
          .close_on_escape = true,
          // The demosaiced RAW is linear sensor data: encode it to sRGB on write. The ISP's NV12
          // is already display-encoded.
          .framebuffer_srgb = opts.raw,
      };
    }
    // How long another camera's layer shows its last frame when no new one arrives. The window
    // renders only while every layer has a frame, so another camera that stops would otherwise
    // stop the window, and the handling of its events, after HoloViz's default 100 ms. (When the
    // first camera stops, so does the window.)
    auto holoviz = graph.op<DisplayOp>(display.name, !opts.headless, std::move(layers),
                                       std::move(sink), viz::LayerTrigger{},
                                       std::chrono::hours(1));

    for (std::size_t layer = 0; layer < display.cameras.size(); ++layer) {
      const std::uint32_t index = display.cameras[layer];
      const CameraInfo& info = infos.at(index);
      const std::string n = std::to_string(index);
      const holoscan::ConnectionOptions& to_display = layer == 0U ? mailbox : side_layer;

      auto capture = graph.op<camera::SIPLCaptureOp>("camera" + n, service, index,
                                               holoscan::MemoryKind::kCudaDevice);
      bind_device("camera" + n, "frame");

      auto sensor_data = graph.op<SIPLCountAndPrintOp>("sensor_data" + n);
      sensor_data.set_params(SensorDataParams{.camera_name = info.output_name,
                                              .print_metadata = opts.print_metadata,
                                              .frame_limit = frame_limit});
      graph.add_flow(capture->sensor_data, sensor_data->input, sensor_data_edge);

      if (!opts.raw) {
        graph.add_flow(capture->frame, holoviz->image_layer_input(layer), to_display);
        continue;
      }
      auto unpack = graph.op<Raw10UnpackOp>("unpack" + n, bayer_encoding(info.bayer_format));
      unpack.set_params(Raw10UnpackParams{
          .max_output_bytes = static_cast<std::uint64_t>(info.width) * info.height * 2U});
      bind_device("unpack" + n, "output");

      auto demosaic = graph.op<holoscan::vision::BayerDemosaicOp>("demosaic" + n);
      demosaic.set_params(holoscan::vision::BayerDemosaicOpParams{
          .bayer_grid_pos = bayer_grid_position(info.bayer_format),
          .generate_alpha = true,
          .alpha_value = 65535U,
      });
      bind_device("demosaic" + n, "output");

      graph.add_flow(capture->frame, unpack->input, mailbox);
      graph.add_flow(unpack->output, demosaic->input, mailbox);
      graph.add_flow(demosaic->output, holoviz->image_layer_input(layer), to_display);
    }

    if (opts.headless) {
      auto discard = graph.op<DiscardImageOp>("discard_" + display.name);
      graph.add_flow(holoviz->output(), discard->input, mailbox);
    }
  }
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));

  return holoscan::compile(graph, std::move(compile_options));
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

// --validate's stand-in for the camera configuration: querying the real one initializes NvSIPL,
// which opens the cameras.
std::vector<CameraInfo> placeholder_cameras() {
  std::vector<CameraInfo> infos(2U);
  for (std::size_t i = 0; i < infos.size(); ++i) {
    infos[i].output_name = "camera" + std::to_string(i);
    infos[i].width = 1920U;
    infos[i].height = 1080U;
    infos[i].bytes_per_line = 2560U;
  }
  return infos;
}

int run_player(const Options& opts, const sigset_t& shutdown_signals) {
  // Constructing the service does not touch NvSIPL; get_camera_info() initializes it.
  auto service = std::make_shared<camera::SIPLCaptureService>(
      opts.camera_config, opts.json_config, /*raw_output=*/opts.raw,
      /*capture_queue_depth=*/4U,
      /*nito_base_path=*/"/var/nvidia/nvcam/settings/sipl",
      camera::SIPLCaptureService::kDefaultTimeoutUs, opts.cuda_device);
  const std::vector<CameraInfo> infos =
      opts.validate ? placeholder_cameras() : service->get_camera_info();
  if (infos.empty()) {
    std::cerr << "sipl_player: the camera configuration has no cameras\n";
    return 1;
  }

  holoscan::Graph graph{"sipl_player"};
  const holoscan::ExecutionPlan plan = compile_player(graph, opts, service, infos);
  if (!plan.ok()) {
    std::cerr << "Graph compilation failed:\n" << plan.json() << "\n";
    return 1;
  }
  if (opts.validate) {
    // Every window's HolovizOp must have the same serial owner (see DisplayOp). Headless
    // HolovizOps render into CUDA images and use no window system, so they may run concurrently.
    std::size_t window_partitions = opts.headless ? 1U : 0U;
    for (const auto partition : plan.partitions()) {
      if (opts.headless) {
        break;
      }
      const auto paths = partition.operator_paths();
      window_partitions += std::any_of(paths.begin(), paths.end(), [](const auto& path) {
        return std::string_view(path).starts_with("holoviz");
      });
    }
    if (window_partitions != 1U) {
      std::cerr << "sipl_player: the HolovizOps are spread over " << window_partitions
                << " execution partitions\n";
      return 1;
    }
    std::cout << "graph validation complete (" << (opts.raw ? "raw" : "isp") << ", "
              << (opts.separate ? "separate" : "tiled") << (opts.headless ? ", headless" : "")
              << ")\n";
    return 0;
  }

  for (const CameraInfo& info : infos) {
    std::cout << "Camera " << info.output_name << ": " << info.width << "x" << info.height
              << (opts.raw ? " RAW10" : " ISP (NV12)") << "\n";
  }
  holoscan::RunSession session = holoscan::run_async(plan);

  // Run until the session ends (a window closed, --frame-limit, or a failure). The first SIGINT or
  // SIGTERM stops it cooperatively, which stops the cameras; a second one ends the process at
  // once.
  bool stopping = false;
  while (session.is_running()) {
    const timespec poll{.tv_sec = 0, .tv_nsec = 100'000'000};
    const int signal_number = sigtimedwait(&shutdown_signals, nullptr, &poll);
    if (signal_number != SIGINT && signal_number != SIGTERM) {
      continue;
    }
    if (stopping) {
      signal(signal_number, SIG_DFL);
      pthread_sigmask(SIG_UNBLOCK, &shutdown_signals, nullptr);
      raise(signal_number);
    }
    stopping = true;
    std::cout << "Stopping...\n";
    session.request_stop();
  }
  session.wait();
  for (const auto& diagnostic : session.diagnostics()) {
    std::cerr << "Session diagnostic: " << holoscan::format_diagnostic(diagnostic, plan.graph())
              << "\n";
  }
  return session.termination() == holoscan::RunTermination::kFailed ? 1 : 0;
}

}  // namespace

int main(int argc, char** argv) {
  // First, before anything starts a thread (CUDA, NvSIPL, the runtime): block SIGINT and SIGTERM
  // in every thread, so that run_player() receives them with sigtimedwait() and stops the
  // session cleanly instead of the process dying mid-capture.
  sigset_t shutdown_signals;
  sigemptyset(&shutdown_signals);
  sigaddset(&shutdown_signals, SIGINT);
  sigaddset(&shutdown_signals, SIGTERM);
  pthread_sigmask(SIG_BLOCK, &shutdown_signals, nullptr);

  const std::string_view prog = argc > 0 ? argv[0] : "sipl_player";
  Options opts;
  try {
    opts = parse_options(argc, argv);
  } catch (const std::invalid_argument& e) {
    std::cerr << "sipl_player: " << e.what() << "\n";
    print_usage(std::cerr, prog);
    return 64;
  }
  if (opts.show_help) {
    print_usage(std::cout, prog);
    return 0;
  }
  try {
    if (opts.list_configs) {
      camera::SIPLCaptureService::list_available_configs(opts.json_config);
      return 0;
    }
    return run_player(opts, shutdown_signals);
  } catch (const std::exception& e) {
    std::cerr << "sipl_player: " << e.what() << "\n";
    return 1;
  }
}
