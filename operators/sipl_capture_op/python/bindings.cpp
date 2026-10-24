// SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// SIPL's Python types in holoscan_camera._camera: SIPLCaptureService, which SIPLCaptureOp takes as
// its `service` constructor handle, and the camera description types.

#include "sipl_capture_op/python/bindings.hpp"

#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <cstdint>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <streambuf>
#include <string>
#include <vector>

#include <holoscan/python/constructor_handle_capsule.hpp>

#include "sipl_capture_op/sipl_capture_service.hpp"
#include "sipl_capture_op/sipl_capture_service_handle.hpp"

namespace nb = nanobind;
using namespace nb::literals;  // NOLINT(build/namespaces_literals)

namespace holoscan::camera {
namespace {

using CameraInfo = SIPLCaptureService::CameraInfo;
using PixelFormat = SIPLCaptureService::PixelFormat;
using BayerFormat = SIPLCaptureService::BayerFormat;

// Points std::cout at another buffer for one scope. std::cout is process-wide, so redirections
// are serialized: overlapping ones would restore each other's buffers out of order.
class CoutRedirect {
 public:
  explicit CoutRedirect(std::streambuf* buffer)
      : lock_(mutex()), previous_(std::cout.rdbuf(buffer)) {}
  ~CoutRedirect() { std::cout.rdbuf(previous_); }
  CoutRedirect(const CoutRedirect&) = delete;
  CoutRedirect& operator=(const CoutRedirect&) = delete;

 private:
  static std::mutex& mutex() {
    static std::mutex instance;
    return instance;
  }

  std::lock_guard<std::mutex> lock_;
  std::streambuf* previous_;
};

// nanobind registers a C++ type once per process. When the module is imported again (after its
// entries are removed from sys.modules), attach the types already registered instead.
bool attach_registered_types(nb::module_& module) {
  const nb::handle service = nb::type<SIPLCaptureService>();
  const nb::handle info = nb::type<CameraInfo>();
  const nb::handle pixel_format = nb::type<PixelFormat>();
  const nb::handle bayer_format = nb::type<BayerFormat>();
  if (!service.is_valid() || !info.is_valid() || !pixel_format.is_valid() ||
      !bayer_format.is_valid()) {
    return false;
  }
  module.attr("SIPLCaptureService") = service;
  module.attr("CameraInfo") = info;
  module.attr("PixelFormat") = pixel_format;
  module.attr("BayerFormat") = bayer_format;
  return true;
}

void define_types(nb::module_& module) {
  nb::enum_<PixelFormat>(module, "PixelFormat")
      .value("RAW_10", PixelFormat::kRaw10)
      .value("RAW_12", PixelFormat::kRaw12);

  // Bayer phase of the RAW frames; the values match holoscan_vision's BayerDemosaicOp
  // bayer_grid_pos.
  nb::enum_<BayerFormat>(module, "BayerFormat")
      .value("BGGR", BayerFormat::kBggr)
      .value("RGGB", BayerFormat::kRggb)
      .value("GBRG", BayerFormat::kGbrg)
      .value("GRBG", BayerFormat::kGrbg);

  nb::class_<CameraInfo>(module, "CameraInfo", "One camera of a SIPL camera configuration.")
      .def(nb::init<>())
      .def_rw("output_name", &CameraInfo::output_name, "The camera's name in the configuration.")
      .def_rw("offset", &CameraInfo::offset, "RAW: byte offset of the first active row.")
      .def_rw("embedded_top_lines", &CameraInfo::embedded_top_lines,
              "RAW: embedded rows before the active rows.")
      .def_rw("embedded_bottom_lines", &CameraInfo::embedded_bottom_lines,
              "RAW: embedded rows after the active rows.")
      .def_rw("width", &CameraInfo::width, "Frame width in pixels.")
      .def_rw("height", &CameraInfo::height, "Frame height in pixels.")
      .def_rw("bytes_per_line", &CameraInfo::bytes_per_line, "RAW: bytes per sensor row.")
      .def_rw("pixel_format", &CameraInfo::pixel_format, "RAW sample format.")
      .def_rw("bayer_format", &CameraInfo::bayer_format, "Bayer phase of the RAW frames.");

  // Constructed through std::make_shared: the service hands out weak references to itself
  // (std::enable_shared_from_this) for frames still in flight.
  nb::class_<SIPLCaptureService>(
      module, "SIPLCaptureService",
      "One NvSIPL camera configuration, shared by the SIPLCaptureOp of each of its cameras.\n\n"
      "Constructing it opens no camera; get_camera_info() initializes NvSIPL.")
      .def(nb::new_([](const std::string& camera_config, const std::string& json_config,
                       bool raw_output, std::uint32_t capture_queue_depth,
                       const std::string& nito_base_path, std::uint32_t timeout_us,
                       std::int32_t cuda_device) {
             return std::make_shared<SIPLCaptureService>(camera_config, json_config, raw_output,
                                                         capture_queue_depth, nito_base_path,
                                                         timeout_us, cuda_device);
           }),
           "camera_config"_a = "", "json_config"_a = "", "raw_output"_a = false,
           "capture_queue_depth"_a = 4U, "nito_base_path"_a = "/var/nvidia/nvcam/settings/sipl",
           "timeout_us"_a = SIPLCaptureService::kDefaultTimeoutUs, "cuda_device"_a = 0,
           "camera_config: configuration name; empty selects the first one found.\n"
           "json_config: vendor JSON platform configuration file, if any.\n"
           "raw_output: deliver the sensor's RAW frames instead of the ISP's NV12.\n"
           "timeout_us: how long to wait for a camera's next frame before the run fails.\n"
           "cuda_device: the CUDA device the frames are imported to.")
      // Holoscan calls this when the service is passed to SIPLCaptureOp as `service=`. The
      // service is created shared-owned (nb::new_ above), so the operator holds the C++ object,
      // not this Python wrapper.
      .def(
          "__holoscan_constructor_handle__",
          [](SIPLCaptureService& self, const std::string& type_name) {
            PyObject* exported = holoscan::python::export_constructor_handle(
                type_name, sipl_capture_service_handle_type(),
                self.shared_from_this());
            if (exported == nullptr) {
              throw nb::python_error();
            }
            return nb::steal(exported);
          },
          "type_name"_a,
          "Holoscan calls this to pass the service to SIPLCaptureOp as a constructor handle.")
      .def_static(
          "list_available_configs",
          [](const std::string& json_config) {
            // NvSIPL's listing is written to std::cout; send it to sys.stdout, where Python's own
            // output and its redirections go, even when the listing then fails.
            std::ostringstream listing;
            const auto print_listing = [&listing] {
              nb::module_::import_("sys").attr("stdout").attr("write")(listing.str());
            };
            try {
              nb::gil_scoped_release release;
              const CoutRedirect redirect{listing.rdbuf()};
              SIPLCaptureService::list_available_configs(json_config);
            } catch (...) {
              print_listing();
              throw;
            }
            print_listing();
          },
          "json_config"_a = "", "Print the available camera configurations.")
      .def(
          "get_camera_info",
          [](SIPLCaptureService& self) {
            std::vector<CameraInfo> infos;
            {
              nb::gil_scoped_release release;
              infos = self.camera_info_snapshot();
            }
            return infos;
          },
          "The configuration's cameras. The first call initializes NvSIPL, which opens them.")
      .def(
          "camera_count",
          [](SIPLCaptureService& self) {
            nb::gil_scoped_release release;
            return self.camera_count();
          },
          "The number of cameras. Initializes NvSIPL like get_camera_info().");
}

}  // namespace

void bind_sipl_types(nb::module_& module) {
  if (!attach_registered_types(module)) {
    define_types(module);
  }
}

}  // namespace holoscan::camera
