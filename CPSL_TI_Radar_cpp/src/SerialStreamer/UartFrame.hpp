#ifndef CPSL_RADAR_UART_FRAME_HPP
#define CPSL_RADAR_UART_FRAME_HPP

// parse_uart_frame: the pure parser of one TI demo frame from the serial data
// port (directive core-16, P8). No I/O, no allocation once `out.points` has
// grown to the largest frame, never reads outside [data, data + len) and
// never throws. SerialStreamer frames the byte stream (magic word, header,
// then exactly totalPacketLen bytes) and hands each frame to it.
//
// Frame layout (little-endian), shared by every dialect:
//
//   magic word  02 01 04 03 06 05 08 07                       8 B
//   header      version, totalPacketLen, platform, frameNumber,
//               timeCpuCycles, numDetectedObj, numTLVs,
//               subFrameNumber (not in sdk2)                  28 or 32 B
//   numTLVs x   {u32 type, u32 length, length bytes of payload}
//   padding     the rest of totalPacketLen (the demos pad to a multiple of 32)
//
// `length` never includes the 8-byte TLV header. TLV types other than the
// detected points (1) and their side info (7) are skipped.

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "BoardDescriptor.hpp"
#include "Status.hpp"

namespace cpsl {
namespace radar {

// One detected point. Which fields a demo fills depends on the TLV dialect
// (docs/ARCHITECTURE.md, "Serial TLV path"): sdk3 sends all six (snr_db and
// noise_db are 0 when the frame has no side info TLV).
struct Point {
    float x = 0, y = 0, z = 0;  // m
    float v = 0;                // radial velocity, m/s
    float snr_db = 0, noise_db = 0;
};

// The frame header after the magic word. sub_frame_number is 0 for sdk2.
struct UartHeader {
    uint32_t version = 0;
    uint32_t total_packet_len = 0;  // whole frame in bytes, magic word and padding included
    uint32_t platform = 0;
    uint32_t frame_number = 0;
    uint32_t time_cpu_cycles = 0;
    uint32_t num_detected_obj = 0;
    uint32_t num_tlvs = 0;
    uint32_t sub_frame_number = 0;
};

// One parsed frame. parse_uart_frame resizes `points` and never shrinks its
// capacity, so reusing one UartFrame allocates nothing after the first frames.
struct UartFrame {
    UartHeader header;
    std::vector<Point> points;
    bool has_side_info = false;  // a TLV 7 filled snr_db/noise_db
};

// The magic word that starts every frame.
extern const uint8_t kUartMagic[8];

// totalPacketLen above this is treated as corrupt (at 3.125 Mbaud this is
// more than 3 s of data; real frames are a few kB).
constexpr uint32_t kUartMaxPacketBytes = 1u << 20;

// Header length (magic word included) of a dialect: 36 for sdk2, else 40.
size_t uart_header_bytes(TlvDialect dialect);

// Offset of the first complete magic word in [data, data + len), or `len`
// if there is none.
size_t find_uart_magic(const uint8_t* data, size_t len);

// Little-endian u32 at data[off] (the caller checks off + 4 <= len).
inline uint32_t uart_le32(const uint8_t* data, size_t off) {
    return static_cast<uint32_t>(data[off]) | (static_cast<uint32_t>(data[off + 1]) << 8) |
           (static_cast<uint32_t>(data[off + 2]) << 16) | (static_cast<uint32_t>(data[off + 3]) << 24);
}

// Parse the frame that starts at data[0]. `len` may extend past the frame
// (e.g. a second frame follows): only the first header.total_packet_len
// bytes are read. On failure `out` holds no valid frame and the Status
// (Code::malformed_frame) says what was wrong:
//   - fewer bytes than the header, or than totalPacketLen;
//   - no magic word at data[0];
//   - totalPacketLen shorter than the header or above kUartMaxPacketBytes;
//   - a TLV header or payload past totalPacketLen, or numTLVs that cannot fit;
//   - two TLVs of type 1, or of type 7;
//   - a points payload that is not a whole number of points, or whose point
//     count differs from numDetectedObj; side info whose count differs from
//     the points'.
Status parse_uart_frame(const uint8_t* data, size_t len, TlvDialect dialect, UartFrame& out);

// The same, returning a new UartFrame (convenient in tests; allocates).
Result<UartFrame> parse_uart_frame(const uint8_t* data, size_t len, TlvDialect dialect);
inline Result<UartFrame> parse_uart_frame(const std::vector<uint8_t>& bytes, TlvDialect dialect) {
    return parse_uart_frame(bytes.data(), bytes.size(), dialect);
}

}  // namespace radar
}  // namespace cpsl

#endif
