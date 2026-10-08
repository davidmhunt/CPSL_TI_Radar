// Serial TLV test fixtures: synthetic TI demo frames (sdk3 and sdk2 layouts),
// a scripted data port (cpsl::radar::ByteStream) and a schema v2 system
// config with serial streaming on. Used by test_uart_parse,
// test_serial_streamer_frames and test_radar_e2e_fake. No port is opened.
#ifndef UART_TEST_FRAMES_HPP
#define UART_TEST_FRAMES_HPP

#include <stdlib.h>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <system_error>
#include <vector>

#include "ByteStream.hpp"
#include "SystemConfigReader.hpp"
#include "TLVProcessing.hpp"

namespace uart_test {

typedef std::vector<uint8_t> Bytes;

inline void put_u16(Bytes& b, uint16_t v) {
    b.push_back(static_cast<uint8_t>(v & 0xFF));
    b.push_back(static_cast<uint8_t>(v >> 8));
}
inline void put_i16(Bytes& b, int16_t v) { put_u16(b, static_cast<uint16_t>(v)); }
inline void put_u32(Bytes& b, uint32_t v) {
    for (int i = 0; i < 4; i++) b.push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}
inline void put_float(Bytes& b, float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    put_u32(b, u);
}

struct Tlv {
    uint32_t type;
    Bytes payload;
};

// Options for a synthetic frame. Defaults give a valid frame.
struct FrameOpts {
    int64_t num_obj = -1;      // numDetectedObj; -1 = from the points TLV
    int64_t num_tlvs = -1;     // numTLVs; -1 = tlvs.size()
    int total_delta = 0;       // added to the true totalPacketLen
    size_t pad_to = 32;        // pad totalPacketLen to a multiple of this (1 = no padding)
    uint32_t platform = 0x000A1843;
};

// SDK 3 TLV 1: n points, float {x, y, z, v} = base + 4*i + {0, 1, 2, 3}
inline Tlv points_tlv(int n, float base) {
    Tlv t{TLVCodes::DETECTED_POINTS, {}};
    for (int i = 0; i < n * 4; i++) put_float(t.payload, base + static_cast<float>(i));
    return t;
}

// TLV 7: n entries, snr = (100 + i) * 0.1 dB, noise = -20 * i * 0.1 dB
inline Tlv side_info_tlv(int n) {
    Tlv t{TLVCodes::DETECTED_POINTS_SIDE_INFO, {}};
    for (int i = 0; i < n; i++) {
        put_i16(t.payload, static_cast<int16_t>(100 + i));
        put_i16(t.payload, static_cast<int16_t>(-20 * i));
    }
    return t;
}

// SDK 2 (xWR14xx) detected object: 12 B on the wire
struct Sdk2Obj {
    uint16_t range_idx;
    int16_t doppler_idx;
    uint16_t peak_val;
    int16_t x, y, z;  // Q-format meters
};

// SDK 2 TLV 1: {u16 numDetetedObj, u16 xyzQFormat} + 12 B per object
inline Tlv sdk2_points_tlv(const std::vector<Sdk2Obj>& objs, uint16_t q) {
    Tlv t{TLVCodes::DETECTED_POINTS, {}};
    put_u16(t.payload, static_cast<uint16_t>(objs.size()));
    put_u16(t.payload, q);
    for (const Sdk2Obj& o : objs) {
        put_u16(t.payload, o.range_idx);
        put_i16(t.payload, o.doppler_idx);
        put_u16(t.payload, o.peak_val);
        put_i16(t.payload, o.x);
        put_i16(t.payload, o.y);
        put_i16(t.payload, o.z);
    }
    return t;
}

// the point count a TLV list implies for numDetectedObj (sdk3: 16 B per
// point; sdk2: from the descriptor)
inline int64_t implied_num_obj(const std::vector<Tlv>& tlvs, bool sdk2) {
    for (const Tlv& t : tlvs) {
        if (t.type != TLVCodes::DETECTED_POINTS) continue;
        if (!sdk2) return static_cast<int64_t>(t.payload.size() / 16);
        if (t.payload.size() >= 2) return t.payload[0] | (t.payload[1] << 8);
    }
    return 0;
}

// A whole frame: magic word, header (36 B for sdk2, else 40 B), TLVs, zero padding.
inline Bytes make_frame(uint32_t frame_number, const std::vector<Tlv>& tlvs, FrameOpts o = FrameOpts(),
                        bool sdk2 = false) {
    Bytes body;
    for (const Tlv& t : tlvs) {
        put_u32(body, t.type);
        put_u32(body, static_cast<uint32_t>(t.payload.size()));
        body.insert(body.end(), t.payload.begin(), t.payload.end());
    }
    const size_t hdr = sdk2 ? 36 : 40;
    size_t total = hdr + body.size();
    if (o.pad_to > 1) total = (total + o.pad_to - 1) / o.pad_to * o.pad_to;
    Bytes f = {2, 1, 4, 3, 6, 5, 8, 7};
    put_u32(f, 0x03060000);  // version
    put_u32(f, static_cast<uint32_t>(static_cast<int64_t>(total) + o.total_delta));
    put_u32(f, o.platform);
    put_u32(f, frame_number);
    put_u32(f, 123456);  // timeCpuCycles
    put_u32(f, static_cast<uint32_t>(o.num_obj >= 0 ? o.num_obj : implied_num_obj(tlvs, sdk2)));
    put_u32(f, static_cast<uint32_t>(o.num_tlvs >= 0 ? o.num_tlvs : static_cast<int64_t>(tlvs.size())));
    if (!sdk2) put_u32(f, 0);  // subFrameNumber
    f.insert(f.end(), body.begin(), body.end());
    f.resize(total, 0);
    return f;
}

inline Bytes cat(const std::vector<Bytes>& parts) {
    Bytes out;
    for (const Bytes& p : parts) out.insert(out.end(), p.begin(), p.end());
    return out;
}

// A scripted serial data port. push() queues bytes; read_some() returns at
// most `max_read` (and `cap`) bytes of the oldest queued chunk, or waits up
// to its timeout. fail() makes every later read return EIO.
class FakeDataPort : public cpsl::radar::ByteStream {
public:
    explicit FakeDataPort(size_t max_read = static_cast<size_t>(-1)) : max_read_(max_read) {}

    void push(const Bytes& b) {
        {
            std::lock_guard<std::mutex> l(m_);
            if (!b.empty()) chunks_.push_back(b);
        }
        cv_.notify_all();
    }
    void fail() {
        {
            std::lock_guard<std::mutex> l(m_);
            failed_ = true;
        }
        cv_.notify_all();
    }
    size_t reads() {
        std::lock_guard<std::mutex> l(m_);
        return reads_;
    }
    // the largest `cap` any read asked for
    size_t max_cap() {
        std::lock_guard<std::mutex> l(m_);
        return max_cap_;
    }

    std::error_code write(const uint8_t*, size_t, std::chrono::milliseconds) override { return {}; }

    std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) override {
        n = 0;
        std::unique_lock<std::mutex> l(m_);
        reads_++;
        max_cap_ = std::max(max_cap_, cap);
        cv_.wait_for(l, timeout, [this] { return failed_ || !chunks_.empty(); });
        if (failed_) return std::error_code(EIO, std::system_category());
        if (chunks_.empty()) return std::make_error_code(std::errc::timed_out);
        Bytes& front = chunks_.front();
        n = std::min({cap, max_read_, front.size()});
        std::memcpy(buf, front.data(), n);
        front.erase(front.begin(), front.begin() + static_cast<std::ptrdiff_t>(n));
        if (front.empty()) chunks_.pop_front();
        return {};
    }

private:
    std::mutex m_;
    std::condition_variable cv_;
    std::deque<Bytes> chunks_;
    size_t max_read_;
    bool failed_ = false;
    size_t reads_ = 0;
    size_t max_cap_ = 0;
};

// Writes <dir>/<name>.json: `board` with serial streaming on (port not
// opened by the tests), DCA1000 off, data_uart.timeout_ms = timeout_ms.
inline std::string write_serial_config(const std::string& name, const std::string& dir,
                                       const std::string& board = "IWR1843", int timeout_ms = 300) {
    setenv(SystemConfigReader::kBoardsDirEnv, (std::string(CONFIG_DIR) + "/boards").c_str(), 1);
    std::string cfg = std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg";
    if (board == "IWR1443") cfg = std::string(TEST_DATA_DIR) + "/radar/iwr1443.cfg";
    if (board == "IWR6843") cfg = std::string(TEST_DATA_DIR) + "/radar/iwr6843.cfg";
    if (board == "AWR2243_CASCADE") cfg = std::string(TEST_DATA_DIR) + "/radar/awr2243_cascade.cfg";
    const std::string path = dir + "/" + name + ".json";
    const std::string firmware = board == "AWR2243_CASCADE" ? "cascade_ddm" : "demo";  // required key (gui-04)
    std::ofstream(path) << "{\"schema_version\": 2, \"board\": \"" << board << "\", \"firmware\": \""
                        << firmware << "\", \"radar_cfg\": \"" << cfg
                        << "\", \"cli\": {\"port\": \"/dev/null-not-opened\"}, "
                        << "\"serial_stream\": {\"enabled\": true, \"port\": \"/dev/null-not-opened\"}, "
                        << "\"dca1000\": {\"enabled\": false}, \"runtime\": {\"firmware_check\": \"off\"}, "
                        << "\"board_overrides\": {\"data_uart\": {\"timeout_ms\": " << timeout_ms << "}}, "
                        << "\"output\": {\"dir\": \"" << dir << "\", \"save_adc_frames\": false, "
                        << "\"save_raw_lvds\": false}}";
    return path;
}

}  // namespace uart_test

#endif  // UART_TEST_FRAMES_HPP
