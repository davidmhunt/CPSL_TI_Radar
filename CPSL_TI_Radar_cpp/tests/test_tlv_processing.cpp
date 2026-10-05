// TLVProcessing: payload decoders for TLV type 1 (detected points) and
// type 7 (side info).
#include "test_harness.hpp"
#include "TLVProcessing.hpp"

#include <cstring>

typedef std::vector<uint8_t> Bytes;

static void put_float_le(Bytes& out, float f) {
    uint32_t u;
    std::memcpy(&u, &f, 4);
    for (int i = 0; i < 4; i++) out.push_back(static_cast<uint8_t>((u >> (8 * i)) & 0xFF));
}

static void put_i16_le(Bytes& out, int16_t v) {
    uint16_t u = static_cast<uint16_t>(v);
    out.push_back(static_cast<uint8_t>(u & 0xFF));
    out.push_back(static_cast<uint8_t>(u >> 8));
}

TEST_CASE(tlv_code_values) {
    CHECK_EQ(TLVCodes::DETECTED_POINTS, 1u);
    CHECK_EQ(TLVCodes::RANGE_PROFILE, 2u);
    CHECK_EQ(TLVCodes::DETECTED_POINTS_SIDE_INFO, 7u);
    CHECK_EQ(TLVCodes::TRACKER, 10u);
    CHECK_EQ(TLVCodes::DETECTED_POINTS_COMPACT, 104u);
}

TEST_CASE(detected_points_default_state) {
    TLVDetectedPoints p;
    CHECK(!p.valid_data);
    CHECK(p.detected_points.empty());
}

TEST_CASE(detected_points_two_points) {
    Bytes b;
    const float pts[2][4] = {{1.5f, -2.25f, 0.5f, 3.0f}, {-10.0f, 20.0f, -0.125f, 0.0f}};
    for (auto& pt : pts)
        for (float f : pt) put_float_le(b, f);

    TLVDetectedPoints p;
    p.process(b);
    CHECK(p.valid_data);
    CHECK_EQ(p.detected_points.size(), static_cast<size_t>(2));
    for (size_t r = 0; r < 2; r++) {
        CHECK_EQ(p.detected_points[r].size(), static_cast<size_t>(4));
        for (size_t c = 0; c < 4; c++) CHECK_EQ(p.detected_points[r][c], pts[r][c]);
    }
}

TEST_CASE(detected_points_empty_payload_is_valid_and_empty) {
    TLVDetectedPoints p;
    Bytes b;
    p.process(b);
    CHECK(p.valid_data);
    CHECK(p.detected_points.empty());
}

TEST_CASE(detected_points_replaces_previous_frame) {
    TLVDetectedPoints p;
    Bytes three;
    for (int i = 0; i < 12; i++) put_float_le(three, static_cast<float>(i));
    p.process(three);
    CHECK_EQ(p.detected_points.size(), static_cast<size_t>(3));
    Bytes one;
    for (int i = 0; i < 4; i++) put_float_le(one, 100.0f + i);
    p.process(one);
    CHECK_EQ(p.detected_points.size(), static_cast<size_t>(1));
    CHECK_EQ(p.detected_points[0][0], 100.0f);
}

TEST_CASE(detected_points_truncated_final_point_is_dropped) {
    // 5 floats = one whole point plus a stray float: the stray float is
    // silently discarded (no error, valid_data still true).
    Bytes b;
    for (int i = 0; i < 5; i++) put_float_le(b, static_cast<float>(i + 1));
    TLVDetectedPoints p;
    p.process(b);
    CHECK(p.valid_data);
    CHECK_EQ(p.detected_points.size(), static_cast<size_t>(1));
    CHECK_EQ(p.detected_points[0][3], 4.0f);
}

TEST_CASE(detected_points_fewer_than_four_floats_gives_no_points) {
    Bytes b;
    for (int i = 0; i < 3; i++) put_float_le(b, 1.0f);
    TLVDetectedPoints p;
    p.process(b);
    CHECK(p.valid_data);
    CHECK(p.detected_points.empty());
}

TEST_CASE(bytes_to_floats_is_little_endian) {
    TLVDetectedPoints p;
    // 1.0f = 0x3F800000 -> 00 00 80 3F on the wire
    Bytes b{0x00, 0x00, 0x80, 0x3F, 0x00, 0x00, 0x00, 0xC0};  // 1.0f, -2.0f
    std::vector<float> f = p.bytes_to_floats(b);
    CHECK_EQ(f.size(), static_cast<size_t>(2));
    CHECK_EQ(f[0], 1.0f);
    CHECK_EQ(f[1], -2.0f);
}

TEST_CASE(detected_points_copy_and_assign) {
    Bytes b;
    for (int i = 0; i < 4; i++) put_float_le(b, static_cast<float>(i));
    TLVDetectedPoints a;
    a.process(b);
    TLVDetectedPoints c(a);
    CHECK(c.valid_data);
    CHECK_EQ(c.detected_points.size(), static_cast<size_t>(1));
    TLVDetectedPoints d;
    d = a;
    CHECK(d.valid_data);
    CHECK_EQ(d.detected_points[0][2], 2.0f);
}

TEST_CASE(side_info_scaled_to_tenth_db) {
    // two points: [snr, noise] int16 in 0.1 dB steps
    Bytes b;
    put_i16_le(b, 125);   // 12.5 dB
    put_i16_le(b, 300);   // 30.0 dB
    put_i16_le(b, -50);   // -5.0 dB
    put_i16_le(b, 0);
    TLVDetectedPointsSideInfo s;
    CHECK(!s.valid_data);
    s.process(b);
    CHECK(s.valid_data);
    CHECK_EQ(s.side_info.size(), static_cast<size_t>(2));
    CHECK_NEAR(s.side_info[0][0], 12.5, 1e-4);
    CHECK_NEAR(s.side_info[0][1], 30.0, 1e-4);
    CHECK_NEAR(s.side_info[1][0], -5.0, 1e-4);
    CHECK_NEAR(s.side_info[1][1], 0.0, 1e-4);
}

TEST_CASE(side_info_empty_and_partial_point) {
    TLVDetectedPointsSideInfo s;
    Bytes empty;
    s.process(empty);
    CHECK(s.valid_data);
    CHECK(s.side_info.empty());

    // 6 bytes = one whole point (4 bytes) + 2 stray bytes, which are ignored
    Bytes b;
    put_i16_le(b, 10);
    put_i16_le(b, 20);
    put_i16_le(b, 30);
    s.process(b);
    CHECK_EQ(s.side_info.size(), static_cast<size_t>(1));
    CHECK_NEAR(s.side_info[0][1], 2.0, 1e-4);
}

TEST_CASE(detected_points_length_not_multiple_of_4_is_rejected) {
    // core-02 UB list: bytes_to_floats read (and wrote) past the end here
    TLVDetectedPoints p;
    Bytes good;
    for (int i = 0; i < 4; i++) put_float_le(good, 1.0f);
    p.process(good);
    CHECK(p.valid_data);
    Bytes b;
    for (int i = 0; i < 4; i++) put_float_le(b, 2.0f);
    b.push_back(0x7F);  // 17 bytes
    p.process(b);
    CHECK(!p.valid_data);
    CHECK(p.detected_points.empty());
    Bytes five(5, 0x11);
    p.process(five);
    CHECK(!p.valid_data);
}

TEST_CASE(bytes_to_floats_reads_whole_words_only) {
    TLVDetectedPoints p;
    Bytes b{0x00, 0x00, 0x80, 0x3F, 0xAA, 0xBB};  // 1.0f + 2 stray bytes
    std::vector<float> f = p.bytes_to_floats(b);
    CHECK_EQ(f.size(), static_cast<size_t>(1));
    CHECK_EQ(f[0], 1.0f);
    Bytes three{1, 2, 3};
    CHECK(p.bytes_to_floats(three).empty());
}

TEST_MAIN()
