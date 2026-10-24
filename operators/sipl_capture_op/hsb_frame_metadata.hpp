// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Self-contained parser for HSB FPGA metadata on Hololink-compatible cameras.
//
// SIPL exposes the blob in the last pitch-sized row of bottom embedded data.
// This is separate from the CPU mapping of the image pixels.
// The HSB record is 128 bytes: 48 bytes of big-endian fields followed by
// 80 bytes of padding. The parser only needs the first 48 bytes of that row.
//
// Binary layout:
//   Offset  Size  Field
//    0       4    flags        uint32 BE
//    4       4    psn          uint32 BE
//    8       4    crc          uint32 BE
//   12       8    timestamp_s  uint64 BE
//   20       4    timestamp_ns uint32 BE
//   24       8    bytes_written uint64 BE
//   32       2    <reserved>   uint16 BE
//   34       2    frame_number uint16 BE
//   36       8    metadata_s   uint64 BE
//   44       4    metadata_ns  uint32 BE
//   48      80    <padding>
//
// No dependency on hololink headers; the layout was derived from
// hololink/src/hololink/core/hololink.cpp::deserialize_metadata().

#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>

namespace holoscan::camera {

inline constexpr std::uint64_t kNanosecondsPerSecond = 1'000'000'000U;

struct HsbFrameMetadata {
  std::uint32_t flags{};
  std::uint32_t psn{};
  std::uint32_t crc{};
  std::uint64_t timestamp_s{};
  std::uint32_t timestamp_ns{};
  std::uint64_t bytes_written{};
  std::uint16_t frame_number{};
  std::uint64_t metadata_s{};
  std::uint32_t metadata_ns{};
};

// The record's HSB timestamp in nanoseconds, or nothing if it holds none or an invalid one.
inline std::optional<std::int64_t> hsb_timestamp_ns(const HsbFrameMetadata& m) noexcept {
  constexpr auto kMax = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
  if (m.timestamp_ns >= kNanosecondsPerSecond ||
      m.timestamp_s > (kMax - m.timestamp_ns) / kNanosecondsPerSecond) return std::nullopt;
  const auto timestamp =
      static_cast<std::int64_t>(m.timestamp_s * kNanosecondsPerSecond + m.timestamp_ns);
  if (timestamp == 0) return std::nullopt;
  return timestamp;
}

// An epoch sanity check, not a PTP-lock test. The host must continuously
// synchronize HSB to CLOCK_REALTIME using NVIDIA's documented -O 0 setup.
inline std::optional<std::int64_t> hsb_timestamp_in_host_epoch(
    const HsbFrameMetadata& m, std::int64_t realtime_ns) noexcept {
  constexpr std::int64_t kMaxHostTimestampDifferenceNs = 1'000'000'000;
  const auto timestamp = hsb_timestamp_ns(m);
  if (realtime_ns < 0 || !timestamp) return std::nullopt;
  const auto difference =
      *timestamp > realtime_ns ? *timestamp - realtime_ns : realtime_ns - *timestamp;
  if (difference > kMaxHostTimestampDifferenceNs) return std::nullopt;
  return timestamp;
}

// Decides what SIPLCaptureOp does with each frame of an HSB camera, by whether its HSB timestamp
// passed hsb_timestamp_in_host_epoch(). A frame that waited in a queue through a stall of more
// than a second fails that check just as one from an unsynchronized HSB does, so a frame without
// a usable timestamp is skipped; the run fails only when none has been usable for kWait, the time
// also allowed at startup.
class HsbTimestampGate {
 public:
  static constexpr std::chrono::seconds kWait{30};
  enum class Decision { kUse, kSkip, kFail };

  Decision on_frame(bool usable, std::chrono::steady_clock::time_point now) noexcept {
    if (usable) {
      reset();
      return Decision::kUse;
    }
    if (!unusable_since_) unusable_since_ = now;
    ++skipped_;
    return now - *unusable_since_ < kWait ? Decision::kSkip : Decision::kFail;
  }

  // Frames without a usable timestamp since the last one with.
  [[nodiscard]] std::uint64_t skipped() const noexcept { return skipped_; }

  void reset() noexcept {
    unusable_since_.reset();
    skipped_ = 0;
  }

 private:
  std::optional<std::chrono::steady_clock::time_point> unusable_since_;
  std::uint64_t skipped_{ 0 };
};

// Only metadata values survive RAW release. Match by nonzero capture-start TSC,
// never by dequeue order: RAW and ISP queues may have dropped different frames.
class HsbMetadataHistory {
 public:
  explicit HsbMetadataHistory(std::size_t capacity) : capacity_(capacity) {}
  void remember(std::uint64_t capture_tsc, HsbFrameMetadata metadata) {
    if (capture_tsc == 0) return;
    entries_[capture_tsc] = metadata;
    while (entries_.size() > capacity_) entries_.erase(entries_.begin());
  }
  std::optional<HsbFrameMetadata> take(std::uint64_t capture_tsc) {
    std::optional<HsbFrameMetadata> result;
    if (auto it = entries_.find(capture_tsc); it != entries_.end()) {
      result = it->second;
    }
    entries_.erase(entries_.begin(), entries_.upper_bound(capture_tsc));
    return result;
  }

 private:
  std::size_t capacity_;
  std::map<std::uint64_t, HsbFrameMetadata> entries_;
};

// Parse the metadata row exposed by SIPL while its RAW buffer is still held.
// Reject truncated records, empty padding and malformed timestamp fractions.
inline std::optional<HsbFrameMetadata> parse_hsb_metadata(
    const std::uint8_t* buf, std::size_t buf_size) {

  constexpr std::size_t kBlobMin = 48;
  if (!buf || buf_size < kBlobMin) {
    return std::nullopt;
  }

  const std::uint8_t* p = buf;

  auto u16 = [](const std::uint8_t* b) -> std::uint16_t {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(b[0]) << 8u) | b[1]);
  };
  auto u32 = [](const std::uint8_t* b) -> std::uint32_t {
    return (static_cast<std::uint32_t>(b[0]) << 24u) |
           (static_cast<std::uint32_t>(b[1]) << 16u) |
           (static_cast<std::uint32_t>(b[2]) <<  8u) | b[3];
  };
  auto u64 = [](const std::uint8_t* b) -> std::uint64_t {
    return (static_cast<std::uint64_t>(b[0]) << 56u) |
           (static_cast<std::uint64_t>(b[1]) << 48u) |
           (static_cast<std::uint64_t>(b[2]) << 40u) |
           (static_cast<std::uint64_t>(b[3]) << 32u) |
           (static_cast<std::uint64_t>(b[4]) << 24u) |
           (static_cast<std::uint64_t>(b[5]) << 16u) |
           (static_cast<std::uint64_t>(b[6]) <<  8u) | b[7];
  };

  HsbFrameMetadata m;
  m.flags         = u32(p +  0);
  m.psn           = u32(p +  4);
  m.crc           = u32(p +  8);
  m.timestamp_s   = u64(p + 12);
  m.timestamp_ns  = u32(p + 20);
  m.bytes_written = u64(p + 24);
  // p + 32: reserved uint16 — skip
  m.frame_number  = u16(p + 34);
  m.metadata_s    = u64(p + 36);
  m.metadata_ns   = u32(p + 44);
  if ((m.timestamp_s == 0 && m.timestamp_ns == 0) ||
      m.timestamp_ns >= kNanosecondsPerSecond || m.metadata_ns >= kNanosecondsPerSecond) {
    return std::nullopt;
  }
  return m;
}

}  // namespace holoscan::camera
