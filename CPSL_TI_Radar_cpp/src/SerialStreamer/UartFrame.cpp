#include "UartFrame.hpp"

#include <cmath>
#include <cstring>
#include <limits>
#include <string>

namespace cpsl {
namespace radar {

const uint8_t kUartMagic[8] = {2, 1, 4, 3, 6, 5, 8, 7};

namespace {

constexpr uint32_t kTlvDetectedPoints = 1;
constexpr uint32_t kTlvSideInfo = 7;
constexpr uint32_t kTlvCascadeCompactPoints = 12;  // mcuplus_cascade, guiMonitor detectedObjects 3
constexpr size_t kNone = static_cast<size_t>(-1);

Status bad(const std::string& why) { return Status(Code::malformed_frame, "UART frame: " + why); }

float le_float(const uint8_t* p) {
    const uint32_t u = uart_le32(p, 0);
    float f;
    std::memcpy(&f, &u, sizeof f);
    return f;
}

int16_t le_i16(const uint8_t* p) {
    return static_cast<int16_t>(static_cast<uint16_t>(p[0] | (p[1] << 8)));
}

// TLV 1, sdk3 layout: float32 {x, y, z, v} per point (16 B)
Status decode_points_sdk3(const uint8_t* p, uint32_t len, uint32_t num_obj, UartFrame& out) {
    if (len % 16 != 0) {
        return bad("points TLV length " + std::to_string(len) + " is not a multiple of 16 (float x, y, z, v)");
    }
    const uint32_t n = len / 16;
    if (n != num_obj) {
        return bad("points TLV holds " + std::to_string(n) + " points but numDetectedObj is " +
                   std::to_string(num_obj));
    }
    out.points.resize(n);
    for (uint32_t i = 0; i < n; i++) {
        const uint8_t* r = p + 16 * static_cast<size_t>(i);
        Point& pt = out.points[i];
        pt.x = le_float(r);
        pt.y = le_float(r + 4);
        pt.z = le_float(r + 8);
        pt.v = le_float(r + 12);
        pt.snr_db = 0.0f;
        pt.noise_db = 0.0f;
    }
    return Status::ok();
}

// TLV 1, sdk2 layout (docs/research/sdk2_uart_format_2026-10-05.md): a
// descriptor {u16 numDetetedObj, u16 xyzQFormat}, then 12 B per object
// {u16 rangeIdx, i16 dopplerIdx, u16 peakVal, i16 x, i16 y, i16 z};
// meters = int16 / 2^xyzQFormat. No velocity, SNR or noise is sent: v,
// snr_db and noise_db are NaN (approved by the user 2026-10-06 for now;
// to be improved, docs/ARCHITECTURE.md).
Status decode_points_sdk2(const uint8_t* p, uint32_t len, uint32_t num_obj, UartFrame& out) {
    if (len < 4) {
        return bad("sdk2 points TLV length " + std::to_string(len) + " is shorter than its 4-byte descriptor");
    }
    const uint32_t n = static_cast<uint32_t>(p[0] | (p[1] << 8));
    const int q = p[2] | (p[3] << 8);
    if (len != 4 + 12 * n) {
        return bad("sdk2 points TLV length " + std::to_string(len) + " does not match its descriptor's " +
                   std::to_string(n) + " objects (4 + 12 x n bytes)");
    }
    if (n != num_obj) {
        return bad("sdk2 points TLV holds " + std::to_string(n) + " objects but numDetectedObj is " +
                   std::to_string(num_obj));
    }
    if (q > 31) {
        return bad("sdk2 xyzQFormat " + std::to_string(q) + " is out of range");
    }
    const float nan = std::numeric_limits<float>::quiet_NaN();
    out.points.resize(n);
    for (uint32_t i = 0; i < n; i++) {
        const uint8_t* r = p + 4 + 12 * static_cast<size_t>(i);
        Point& pt = out.points[i];
        pt.x = std::ldexp(static_cast<float>(le_i16(r + 6)), -q);
        pt.y = std::ldexp(static_cast<float>(le_i16(r + 8)), -q);
        pt.z = std::ldexp(static_cast<float>(le_i16(r + 10)), -q);
        pt.v = nan;
        pt.snr_db = nan;
        pt.noise_db = nan;
    }
    return Status::ok();
}

// TLV 7: int16 {snr, noise} per point in 0.1 dB (4 B)
Status decode_side_info(const uint8_t* p, uint32_t len, UartFrame& out) {
    if (len % 4 != 0) {
        return bad("side info TLV length " + std::to_string(len) + " is not a multiple of 4 (int16 snr, noise)");
    }
    if (len / 4 != out.points.size()) {
        return bad("side info TLV holds " + std::to_string(len / 4) + " entries for " +
                   std::to_string(out.points.size()) + " points");
    }
    for (size_t i = 0; i < out.points.size(); i++) {
        out.points[i].snr_db = static_cast<float>(le_i16(p + 4 * i)) * 0.1f;
        out.points[i].noise_db = static_cast<float>(le_i16(p + 4 * i + 2)) * 0.1f;
    }
    out.has_side_info = true;
    return Status::ok();
}

}  // namespace

size_t uart_header_bytes(TlvDialect dialect) { return dialect == TlvDialect::sdk2 ? 36 : 40; }

size_t find_uart_magic(const uint8_t* data, size_t len) {
    if (len < sizeof kUartMagic) return len;
    for (size_t i = 0; i + sizeof kUartMagic <= len; i++) {
        if (data[i] == kUartMagic[0] && std::memcmp(data + i, kUartMagic, sizeof kUartMagic) == 0) return i;
    }
    return len;
}

Status parse_uart_frame(const uint8_t* data, size_t len, TlvDialect dialect, UartFrame& out) {
    out.points.clear();
    out.has_side_info = false;
    out.compact_points_skipped = false;
    out.header = UartHeader();
    const size_t hdr = uart_header_bytes(dialect);
    if (data == nullptr || len < hdr) {
        return bad("truncated header: " + std::to_string(len) + " of " + std::to_string(hdr) + " bytes");
    }
    if (std::memcmp(data, kUartMagic, sizeof kUartMagic) != 0) {
        return bad("no magic word at the start of the frame");
    }

    UartHeader h;
    h.version = uart_le32(data, 8);
    h.total_packet_len = uart_le32(data, 12);
    h.platform = uart_le32(data, 16);
    h.frame_number = uart_le32(data, 20);
    h.time_cpu_cycles = uart_le32(data, 24);
    h.num_detected_obj = uart_le32(data, 28);
    h.num_tlvs = uart_le32(data, 32);
    h.sub_frame_number = hdr >= 40 ? uart_le32(data, 36) : 0;

    const size_t total = h.total_packet_len;
    if (total < hdr) {
        return bad("totalPacketLen " + std::to_string(total) + " is shorter than the " + std::to_string(hdr) +
                   "-byte header");
    }
    if (total > kUartMaxPacketBytes) {
        return bad("totalPacketLen " + std::to_string(total) + " is above " + std::to_string(kUartMaxPacketBytes));
    }
    if (len < total) {
        return bad("truncated frame: " + std::to_string(len) + " of " + std::to_string(total) + " bytes");
    }
    if (h.num_tlvs > (total - hdr) / 8) {
        return bad("numTLVs " + std::to_string(h.num_tlvs) + " cannot fit in " + std::to_string(total - hdr) +
                   " bytes");
    }

    // walk the TLVs: bounds first, decode after (a TLV 7 may precede its TLV 1)
    size_t off = hdr;
    size_t points_at = kNone, side_at = kNone;
    uint32_t points_len = 0, side_len = 0;
    for (uint32_t i = 0; i < h.num_tlvs; i++) {
        if (total - off < 8) {
            return bad("TLV " + std::to_string(i) + " header runs past totalPacketLen " + std::to_string(total));
        }
        const uint32_t type = uart_le32(data, off);
        const uint32_t length = uart_le32(data, off + 4);
        if (length > total - off - 8) {
            return bad("TLV " + std::to_string(i) + " (type " + std::to_string(type) + ") length " +
                       std::to_string(length) + " runs past totalPacketLen " + std::to_string(total));
        }
        if (type == kTlvDetectedPoints) {
            if (points_at != kNone) return bad("two detected-points TLVs (type 1)");
            points_at = off + 8;
            points_len = length;
        } else if (type == kTlvSideInfo && dialect != TlvDialect::sdk2) {  // SDK 2 has no type 7
            if (side_at != kNone) return bad("two side info TLVs (type 7)");
            side_at = off + 8;
            side_len = length;
        } else if (type == kTlvCascadeCompactPoints && dialect == TlvDialect::mcuplus_cascade) {
            out.compact_points_skipped = true;
        }
        off += 8 + static_cast<size_t>(length);
    }
    // bytes from `off` to `total` are padding

    if (points_at != kNone) {
        // sdk3 and mcuplus_cascade share the type 1 and 7 layouts
        Status s = dialect == TlvDialect::sdk2
                       ? decode_points_sdk2(data + points_at, points_len, h.num_detected_obj, out)
                       : decode_points_sdk3(data + points_at, points_len, h.num_detected_obj, out);
        if (!s) {
            out.points.clear();
            return s;
        }
        if (side_at != kNone) {
            s = decode_side_info(data + side_at, side_len, out);
            if (!s) {
                out.points.clear();
                out.has_side_info = false;
                return s;
            }
        }
    }
    out.header = h;
    return Status::ok();
}

Result<UartFrame> parse_uart_frame(const uint8_t* data, size_t len, TlvDialect dialect) {
    UartFrame f;
    Status s = parse_uart_frame(data, len, dialect, f);
    if (!s) return s;
    return f;
}

}  // namespace radar
}  // namespace cpsl
