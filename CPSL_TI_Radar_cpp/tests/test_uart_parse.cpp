// parse_uart_frame (UartFrame.hpp): the pure serial frame parser, on golden
// and malformed frames. No port, no SerialStreamer.
#include "test_harness.hpp"
#include "uart_test_frames.hpp"

#include "UartFrame.hpp"

#include <cmath>
#include <random>

using namespace uart_test;
using cpsl::radar::Code;
using cpsl::radar::TlvDialect;
using cpsl::radar::UartFrame;
using cpsl::radar::parse_uart_frame;

namespace {

bool rejected(const Bytes& b, const char* why_part, TlvDialect d = TlvDialect::sdk3) {
    auto r = parse_uart_frame(b, d);
    if (r) return false;
    if (r.status.code != Code::malformed_frame) return false;
    if (r.status.message.find(why_part) == std::string::npos) {
        std::fprintf(stderr, "    message: %s\n", r.status.message.c_str());
        return false;
    }
    return true;
}

}  // namespace

// ---- SDK 3 golden frames ----

TEST_CASE(sdk3_golden_frame_from_literal_bytes) {
    // one point {1.0, 2.0, 0.5, -1.0} with side info {12.5 dB, 30.0 dB},
    // written out by hand (not with the test builder): 40 + 24 + 12 = 76
    // bytes, padded to 96
    const Bytes f = {
        0x02, 0x01, 0x04, 0x03, 0x06, 0x05, 0x08, 0x07,  // magic
        0x00, 0x00, 0x06, 0x03,                          // version 3.6.0.0
        0x60, 0x00, 0x00, 0x00,                          // totalPacketLen 96
        0x43, 0x18, 0x0A, 0x00,                          // platform 0xA1843
        0x2A, 0x00, 0x00, 0x00,                          // frameNumber 42
        0x10, 0x27, 0x00, 0x00,                          // timeCpuCycles 10000
        0x01, 0x00, 0x00, 0x00,                          // numDetectedObj 1
        0x02, 0x00, 0x00, 0x00,                          // numTLVs 2
        0x03, 0x00, 0x00, 0x00,                          // subFrameNumber 3
        0x01, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00,  // TLV 1, length 16
        0x00, 0x00, 0x80, 0x3F,                          // x 1.0
        0x00, 0x00, 0x00, 0x40,                          // y 2.0
        0x00, 0x00, 0x00, 0x3F,                          // z 0.5
        0x00, 0x00, 0x80, 0xBF,                          // v -1.0
        0x07, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00,  // TLV 7, length 4
        0x7D, 0x00, 0x2C, 0x01,                          // snr 125, noise 300 (0.1 dB)
        0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE,  // 20 pad bytes (any value)
        0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE, 0xEE,
        0xEE, 0xEE, 0xEE, 0xEE,
    };
    CHECK_EQ(f.size(), static_cast<size_t>(96));
    auto r = parse_uart_frame(f, TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK_EQ(r->header.version, 0x03060000u);
    CHECK_EQ(r->header.total_packet_len, 96u);
    CHECK_EQ(r->header.platform, 0x000A1843u);
    CHECK_EQ(r->header.frame_number, 42u);
    CHECK_EQ(r->header.time_cpu_cycles, 10000u);
    CHECK_EQ(r->header.num_detected_obj, 1u);
    CHECK_EQ(r->header.num_tlvs, 2u);
    CHECK_EQ(r->header.sub_frame_number, 3u);
    CHECK_EQ(r->points.size(), static_cast<size_t>(1));
    CHECK_EQ(r->points[0].x, 1.0f);
    CHECK_EQ(r->points[0].y, 2.0f);
    CHECK_EQ(r->points[0].z, 0.5f);
    CHECK_EQ(r->points[0].v, -1.0f);
    CHECK_NEAR(r->points[0].snr_db, 12.5, 1e-4);
    CHECK_NEAR(r->points[0].noise_db, 30.0, 1e-4);
    CHECK(r->has_side_info);
    // the test builder lays out the same magic word, length and TLVs
    Bytes p;
    for (float v : {1.0f, 2.0f, 0.5f, -1.0f}) put_float(p, v);
    Bytes s;
    put_i16(s, 125);
    put_i16(s, 300);
    FrameOpts o;
    o.platform = 0x000A1843;
    Bytes built = make_frame(42, {{1, p}, {7, s}}, o);
    CHECK_EQ(built.size(), f.size());
    CHECK(std::equal(built.begin(), built.begin() + 8, f.begin()));
    CHECK(std::equal(built.begin() + 12, built.begin() + 16, f.begin() + 12));
    CHECK(std::equal(built.begin() + 28, built.begin() + 36, f.begin() + 28));  // numDetectedObj, numTLVs
    CHECK(std::equal(built.begin() + 40, built.begin() + 76, f.begin() + 40));  // TLVs
}

TEST_CASE(sdk3_frame_points_side_info_and_skipped_types) {
    Tlv stats{TLVCodes::STATS, Bytes(24, 0x11)};
    Tlv heat{TLVCodes::RANGE_DOPPLER_HEAT_MAP, Bytes(64, 0x22)};
    auto r = parse_uart_frame(make_frame(9, {points_tlv(3, 10.0f), heat, side_info_tlv(3), stats}),
                              TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK_EQ(r->points.size(), static_cast<size_t>(3));
    CHECK_EQ(r->points[2].x, 18.0f);
    CHECK_EQ(r->points[2].v, 21.0f);
    CHECK_NEAR(r->points[2].snr_db, 10.2, 1e-4);
    CHECK_NEAR(r->points[2].noise_db, -4.0, 1e-4);
}

TEST_CASE(sdk3_without_side_info_has_zero_snr_and_noise) {
    auto r = parse_uart_frame(make_frame(1, {points_tlv(2, 0.0f)}), TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK(!r->has_side_info);
    CHECK_EQ(r->points[1].snr_db, 0.0f);
    CHECK_EQ(r->points[1].noise_db, 0.0f);
}

TEST_CASE(side_info_before_points_is_still_matched) {
    auto r = parse_uart_frame(make_frame(1, {side_info_tlv(2), points_tlv(2, 0.0f)}), TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK_NEAR(r->points[1].snr_db, 10.1, 1e-4);
}

TEST_CASE(no_tlvs_and_no_padding_are_valid) {
    FrameOpts o;
    o.pad_to = 1;
    auto r = parse_uart_frame(make_frame(1, {}, o), TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    if (r) CHECK(r->points.empty());
}

// ---- truncation and bounds ----

TEST_CASE(truncated_header_is_rejected) {
    const Bytes f = make_frame(1, {points_tlv(1, 0.0f)});
    CHECK(rejected(Bytes(f.begin(), f.begin() + 39), "truncated header"));
    CHECK(rejected(Bytes(), "truncated header"));
}

TEST_CASE(truncated_frame_is_rejected) {
    const Bytes f = make_frame(1, {points_tlv(2, 0.0f)});
    CHECK(rejected(Bytes(f.begin(), f.end() - 1), "truncated frame"));
}

TEST_CASE(truncated_tlv_is_rejected) {
    // the TLV's length runs past totalPacketLen
    FrameOpts o;
    o.pad_to = 1;
    Bytes f = make_frame(1, {points_tlv(2, 0.0f)}, o);
    f[44] = 0x30;  // length 32 -> 48
    CHECK(rejected(f, "runs past totalPacketLen"));
    // a TLV header that does not fit: numTLVs says 3, one is present
    FrameOpts three;
    three.num_tlvs = 3;
    three.pad_to = 1;
    CHECK(rejected(make_frame(1, {points_tlv(1, 0.0f)}, three), "header runs past totalPacketLen"));
}

TEST_CASE(every_truncation_of_a_valid_frame_is_rejected) {
    // also under ASan: no out-of-bounds read at any length
    const Bytes f = make_frame(5, {points_tlv(4, 1.0f), side_info_tlv(4)});
    UartFrame out;
    for (size_t n = 0; n < f.size(); n++) {
        const auto s = parse_uart_frame(f.data(), n, TlvDialect::sdk3, out);
        CHECK(!s);
    }
    CHECK(static_cast<bool>(parse_uart_frame(f.data(), f.size(), TlvDialect::sdk3, out)));
}

TEST_CASE(random_corruption_never_crashes) {
    // byte flips in a valid frame: any Status is fine, a crash or OOB read is not
    const Bytes good = make_frame(5, {points_tlv(4, 1.0f), side_info_tlv(4), {6, Bytes(24, 1)}});
    std::mt19937 rng(16);
    UartFrame out;
    size_t ok = 0;
    for (int i = 0; i < 20000; i++) {
        Bytes f = good;
        const int flips = 1 + static_cast<int>(rng() % 4);
        for (int k = 0; k < flips; k++) f[rng() % f.size()] = static_cast<uint8_t>(rng());
        const size_t len = (rng() % 4 == 0) ? rng() % f.size() : f.size();
        if (parse_uart_frame(f.data(), len, TlvDialect::sdk3, out)) ok++;
    }
    CHECK(ok > 0);  // flips in the padding or values keep the frame valid
}

TEST_CASE(header_values_out_of_range_are_rejected) {
    Bytes f = make_frame(1, {});
    f[0] = 0x03;
    CHECK(rejected(f, "no magic word"));
    FrameOpts small;
    small.total_delta = -30;  // 64 -> 34
    CHECK(rejected(make_frame(1, {}, small), "shorter than the 40-byte header"));
    Bytes huge = make_frame(1, {});
    huge[12] = 0xFF;
    huge[13] = 0xFF;
    huge[14] = 0xFF;
    huge[15] = 0x7F;
    CHECK(rejected(huge, "is above"));
    FrameOpts many;
    many.num_tlvs = 1000000;
    CHECK(rejected(make_frame(1, {}, many), "numTLVs 1000000 cannot fit"));
}

// ---- payload checks (core-11 review: lengths and numDetectedObj) ----

TEST_CASE(points_tlv_length_not_divisible_by_4_or_16_is_rejected) {
    CHECK(rejected(make_frame(1, {{1, Bytes(6, 0x41)}}), "not a multiple of 16"));   // not of 4
    CHECK(rejected(make_frame(1, {{1, Bytes(20, 0x41)}}), "not a multiple of 16"));  // of 4, not of 16
    CHECK(rejected(make_frame(1, {points_tlv(1, 0.0f), {7, Bytes(6, 0)}}), "not a multiple of 4"));
}

TEST_CASE(wrong_num_detected_obj_is_rejected) {
    FrameOpts o;
    o.num_obj = 3;
    CHECK(rejected(make_frame(1, {points_tlv(2, 0.0f)}, o), "numDetectedObj is 3"));
    // side info for a different number of points
    CHECK(rejected(make_frame(1, {points_tlv(2, 0.0f), side_info_tlv(3)}), "3 entries for 2 points"));
    // a frame without a points TLV may report detections (guiMonitor detectedObjects off)
    FrameOpts five;
    five.num_obj = 5;
    CHECK(static_cast<bool>(parse_uart_frame(make_frame(1, {}, five), TlvDialect::sdk3)));
}

TEST_CASE(duplicate_points_or_side_info_tlv_is_rejected) {
    FrameOpts o;
    o.num_obj = 1;
    CHECK(rejected(make_frame(1, {points_tlv(1, 0.0f), points_tlv(1, 0.0f)}, o), "two detected-points"));
    CHECK(rejected(make_frame(1, {points_tlv(1, 0.0f), side_info_tlv(1), side_info_tlv(1)}), "two side info"));
}

// ---- framing helpers ----

TEST_CASE(garbage_before_the_magic_word) {
    const Bytes f = make_frame(3, {points_tlv(1, 0.0f)});
    const Bytes junk = {0x00, 0x02, 0x01, 0x04, 0x03, 0x06, 0x05, 0x08, 0xFF};  // a near-magic
    const Bytes b = cat({junk, f});
    CHECK_EQ(cpsl::radar::find_uart_magic(b.data(), b.size()), junk.size());
    CHECK(rejected(b, "no magic word"));
    auto r = parse_uart_frame(b.data() + junk.size(), b.size() - junk.size(), TlvDialect::sdk3);
    CHECK(static_cast<bool>(r));
    // a magic word cut off at the end is not found
    const Bytes cut = {0x02, 0x01, 0x04, 0x03, 0x06, 0x05, 0x08};
    CHECK_EQ(cpsl::radar::find_uart_magic(cut.data(), cut.size()), cut.size());
}

TEST_CASE(two_frames_back_to_back_in_one_read) {
    const Bytes a = make_frame(1, {points_tlv(1, 1.0f)});
    const Bytes b = make_frame(2, {points_tlv(2, 2.0f)});
    const Bytes both = cat({a, b});
    UartFrame f;
    CHECK(static_cast<bool>(parse_uart_frame(both.data(), both.size(), TlvDialect::sdk3, f)));
    CHECK_EQ(f.header.frame_number, 1u);
    CHECK_EQ(f.header.total_packet_len, static_cast<uint32_t>(a.size()));
    const size_t next = f.header.total_packet_len;
    CHECK_EQ(cpsl::radar::find_uart_magic(both.data() + next, both.size() - next), static_cast<size_t>(0));
    CHECK(static_cast<bool>(parse_uart_frame(both.data() + next, both.size() - next, TlvDialect::sdk3, f)));
    CHECK_EQ(f.header.frame_number, 2u);
    CHECK_EQ(f.points.size(), static_cast<size_t>(2));
}

TEST_CASE(reused_frame_keeps_its_buffer) {
    UartFrame f;
    const Bytes big = make_frame(1, {points_tlv(8, 0.0f)});
    const Bytes small = make_frame(2, {points_tlv(2, 0.0f)});
    CHECK(static_cast<bool>(parse_uart_frame(big.data(), big.size(), TlvDialect::sdk3, f)));
    const cpsl::radar::Point* p = f.points.data();
    CHECK(static_cast<bool>(parse_uart_frame(small.data(), small.size(), TlvDialect::sdk3, f)));
    CHECK(f.points.data() == p);
    CHECK(static_cast<bool>(parse_uart_frame(big.data(), big.size(), TlvDialect::sdk3, f)));
    CHECK(f.points.data() == p);
    // a rejected frame leaves no points behind
    const Bytes bad = make_frame(3, {{1, Bytes(20, 0)}});
    CHECK(!parse_uart_frame(bad.data(), bad.size(), TlvDialect::sdk3, f));
    CHECK(f.points.empty());
}

TEST_CASE(header_bytes_per_dialect) {
    CHECK_EQ(cpsl::radar::uart_header_bytes(TlvDialect::sdk3), static_cast<size_t>(40));
    CHECK_EQ(cpsl::radar::uart_header_bytes(TlvDialect::mcuplus_cascade), static_cast<size_t>(40));
    CHECK_EQ(cpsl::radar::uart_header_bytes(TlvDialect::sdk2), static_cast<size_t>(36));
}

TEST_MAIN()
