// SerialStreamer frame parsing (header + TLV loop) on synthetic message buffers.
//
// SerialStreamer's parsing methods are private and its only input path is a
// real serial port. These tests never open a port: a default-constructed
// streamer is fed a hand-built message buffer, and the private methods are
// reached by exposing them with `#define private public` while including the
// header. That hack goes away once core-03 splits the parser from the port.
#include <boost/asio.hpp>
#include <algorithm>
#include <bitset>
#include <cstdint>
#include <endian.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <vector>
#define private public
#include "SerialStreamer.hpp"
#undef private

#include "test_harness.hpp"

#include <cstring>

typedef std::vector<uint8_t> Bytes;

static void put_u32(Bytes& b, uint32_t v) {
    for (int i = 0; i < 4; i++) b.push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

static void put_float(Bytes& b, float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    put_u32(b, u);
}

static void put_i16(Bytes& b, int16_t v) {
    uint16_t u = static_cast<uint16_t>(v);
    b.push_back(static_cast<uint8_t>(u & 0xFF));
    b.push_back(static_cast<uint8_t>(u >> 8));
}

struct Tlv { uint32_t type; Bytes payload; };

// Builds the buffer get_next_serial_frame() would hand over: the 32-byte
// header (the preceding magic word was consumed by the previous read), the
// TLVs, then the NEXT frame's 8-byte magic word that terminated the read.
// totalPacketLen counts the whole frame including its own leading magic word.
static Bytes make_message(uint32_t frame_number, const std::vector<Tlv>& tlvs,
                          int total_len_delta = 0, int num_tlvs_override = -1) {
    Bytes body;
    for (const Tlv& t : tlvs) {
        put_u32(body, t.type);
        put_u32(body, static_cast<uint32_t>(t.payload.size()));
        body.insert(body.end(), t.payload.begin(), t.payload.end());
    }
    const size_t msg_len = 32 + body.size() + 8;
    Bytes m;
    put_u32(m, 0x01020304);  // version
    put_u32(m, static_cast<uint32_t>(static_cast<int>(msg_len) + total_len_delta));
    put_u32(m, 0x000A1843);  // platform
    put_u32(m, frame_number);
    put_u32(m, 123456);      // time (cpu cycles)
    put_u32(m, 0);           // numDetectedObj
    put_u32(m, num_tlvs_override >= 0 ? static_cast<uint32_t>(num_tlvs_override)
                                      : static_cast<uint32_t>(tlvs.size()));
    put_u32(m, 0);           // subFrameNumber
    m.insert(m.end(), body.begin(), body.end());
    const char magic[8] = {2, 1, 4, 3, 6, 5, 8, 7};
    m.insert(m.end(), magic, magic + 8);
    return m;
}

static Tlv points_tlv(int n, float base) {
    Tlv t{TLVCodes::DETECTED_POINTS, {}};
    for (int i = 0; i < n * 4; i++) put_float(t.payload, base + static_cast<float>(i));
    return t;
}

static Tlv side_info_tlv(int n) {
    Tlv t{TLVCodes::DETECTED_POINTS_SIDE_INFO, {}};
    for (int i = 0; i < n; i++) {
        put_i16(t.payload, static_cast<int16_t>(100 + i));   // snr
        put_i16(t.payload, static_cast<int16_t>(-20 * i));   // noise
    }
    return t;
}

// feed a message through the same two steps process_next_message() uses
static bool feed(SerialStreamer& s, const Bytes& msg, bool* tlvs_ok = nullptr) {
    s.serial_message_data_buffer = msg;
    if (!s.process_message_header()) return false;
    bool ok = s.process_TLV_messages();
    if (tlvs_ok) *tlvs_ok = ok;
    return true;
}

TEST_CASE(magic_word_matches_ti_demo) {
    SerialStreamer s;
    CHECK_EQ(s.magic_word.size(), static_cast<size_t>(8));
    const uint8_t expected[8] = {2, 1, 4, 3, 6, 5, 8, 7};
    for (size_t i = 0; i < 8; i++) CHECK_EQ(static_cast<uint8_t>(s.magic_word[i]), expected[i]);
}

TEST_CASE(default_streamer_is_uninitialized) {
    SerialStreamer s;
    CHECK(!s.initialized);
    CHECK(!s.check_new_frame_available());
    CHECK_EQ(s.get_missed_frame_count(), 0u);
}

TEST_CASE(valid_frame_points_and_side_info) {
    SerialStreamer s;
    bool tlvs_ok = false;
    CHECK(feed(s, make_message(7, {points_tlv(2, 1.0f), side_info_tlv(2)}), &tlvs_ok));
    CHECK(tlvs_ok);
    CHECK_EQ(s.get_latest_frame_number(), 7u);

    auto side = s.tlv_get_latest_detected_points_side_info();
    CHECK_EQ(side.size(), static_cast<size_t>(2));
    CHECK_NEAR(side[0][0], 10.0, 1e-4);   // 100 * 0.1
    CHECK_NEAR(side[1][0], 10.1, 1e-4);
    CHECK_NEAR(side[1][1], -2.0, 1e-4);

    auto pts = s.tlv_get_latest_detected_points();
    CHECK_EQ(pts.size(), static_cast<size_t>(2));
    CHECK_EQ(pts[0][0], 1.0f);
    CHECK_EQ(pts[1][3], 8.0f);
}

TEST_CASE(frame_without_tlvs_is_valid_and_empty) {
    SerialStreamer s;
    bool tlvs_ok = false;
    CHECK(feed(s, make_message(1, {}), &tlvs_ok));
    CHECK(tlvs_ok);
    CHECK(s.tlv_get_latest_detected_points().empty());
}

TEST_CASE(unknown_tlv_types_are_skipped) {
    SerialStreamer s;
    Tlv range_profile{TLVCodes::RANGE_PROFILE, Bytes(16, 0xEE)};
    bool tlvs_ok = false;
    CHECK(feed(s, make_message(1, {range_profile, points_tlv(1, 5.0f)}), &tlvs_ok));
    CHECK(tlvs_ok);
    auto pts = s.tlv_get_latest_detected_points();
    CHECK_EQ(pts.size(), static_cast<size_t>(1));
    CHECK_EQ(pts[0][0], 5.0f);
}

TEST_CASE(stale_points_cleared_when_next_frame_has_none) {
    SerialStreamer s;
    CHECK(feed(s, make_message(1, {points_tlv(3, 0.0f), side_info_tlv(3)})));
    CHECK_EQ(s.tlv_get_latest_detected_points_side_info().size(), static_cast<size_t>(3));
    CHECK(feed(s, make_message(2, {})));
    CHECK(s.tlv_get_latest_detected_points().empty());
    CHECK(s.tlv_get_latest_detected_points_side_info().empty());
}

TEST_CASE(header_rejected_when_total_length_mismatches) {
    SerialStreamer s;
    CHECK(!feed(s, make_message(1, {points_tlv(1, 0.0f)}, +4)));
    CHECK(!feed(s, make_message(1, {points_tlv(1, 0.0f)}, -4)));
}

TEST_CASE(header_rejected_when_message_too_short) {
    SerialStreamer s;
    s.serial_message_data_buffer = Bytes(8, 0);  // e.g. the first read: junk + magic
    CHECK(!s.process_message_header());
    s.serial_message_data_buffer = Bytes(32, 0);  // exactly one header, nothing else
    CHECK(!s.process_message_header());
}

TEST_CASE(missed_frames_counted_from_frame_number_gaps) {
    SerialStreamer s;
    CHECK(feed(s, make_message(10, {})));
    CHECK_EQ(s.get_missed_frame_count(), 0u);  // first frame: nothing to compare
    CHECK(feed(s, make_message(11, {})));
    CHECK_EQ(s.get_missed_frame_count(), 0u);
    CHECK(feed(s, make_message(14, {})));      // 12, 13 missed
    CHECK_EQ(s.get_missed_frame_count(), 2u);
    CHECK(feed(s, make_message(15, {})));
    CHECK_EQ(s.get_missed_frame_count(), 2u);
}

TEST_CASE(invalid_frames_do_not_update_gap_tracking) {
    SerialStreamer s;
    CHECK(feed(s, make_message(1, {})));
    CHECK(!feed(s, make_message(5, {}, +1)));  // bad length: ignored for tracking
    CHECK(feed(s, make_message(2, {})));
    CHECK_EQ(s.get_missed_frame_count(), 0u);
}

TEST_CASE(tlv_header_past_end_of_message_rejected) {
    SerialStreamer s;
    // header says 3 TLVs but only one is present
    bool tlvs_ok = true;
    CHECK(feed(s, make_message(1, {points_tlv(1, 0.0f)}, 0, 3), &tlvs_ok));
    CHECK(!tlvs_ok);
}

TEST_CASE(tlv_length_past_end_of_message_rejected) {
    SerialStreamer s;
    Bytes msg = make_message(1, {points_tlv(2, 0.0f)});
    // inflate the TLV length field (bytes 36..39) beyond the message
    msg[36] = 0xFF;
    msg[37] = 0xFF;
    bool tlvs_ok = true;
    CHECK(feed(s, msg, &tlvs_ok));
    CHECK(!tlvs_ok);
}

TEST_CASE(rejected_frame_number_is_never_reported_as_latest) {
    // core-02 KNOWN_BUG, fixed: header fields were stored before the length
    // check, so get_latest_frame_number() returned a rejected frame's number
    SerialStreamer s;
    CHECK(feed(s, make_message(3, {})));
    CHECK(!feed(s, make_message(99, {}, +4)));
    CHECK_EQ(s.get_latest_frame_number(), 3u);
}

TEST_CASE(frame_with_bad_tlv_publishes_nothing) {
    // valid header, broken TLV: the previous frame's number and points stay
    SerialStreamer s;
    CHECK(feed(s, make_message(5, {points_tlv(2, 1.0f), side_info_tlv(2)})));
    bool tlvs_ok = true;
    CHECK(feed(s, make_message(6, {points_tlv(1, 9.0f)}, 0, 3), &tlvs_ok));
    CHECK(!tlvs_ok);
    CHECK_EQ(s.get_latest_frame_number(), 5u);
    CHECK_EQ(s.tlv_get_latest_detected_points().size(), static_cast<size_t>(2));
    CHECK_EQ(s.tlv_get_latest_detected_points_side_info().size(), static_cast<size_t>(2));
    // and it is not counted for frame-number gaps: 7 follows 5 with 6 missed
    CHECK(feed(s, make_message(7, {})));
    CHECK_EQ(s.get_missed_frame_count(), 1u);
}

TEST_CASE(points_tlv_length_not_multiple_of_4_rejects_the_frame) {
    // core-02 UB list: a 6-byte points payload went through bytes_to_floats
    SerialStreamer s;
    CHECK(feed(s, make_message(1, {points_tlv(1, 2.0f)})));
    Tlv odd{TLVCodes::DETECTED_POINTS, Bytes(6, 0x41)};
    bool tlvs_ok = true;
    CHECK(feed(s, make_message(2, {odd}), &tlvs_ok));
    CHECK(!tlvs_ok);
    CHECK_EQ(s.get_latest_frame_number(), 1u);
    CHECK_EQ(s.tlv_get_latest_detected_points().size(), static_cast<size_t>(1));
}

TEST_MAIN()
