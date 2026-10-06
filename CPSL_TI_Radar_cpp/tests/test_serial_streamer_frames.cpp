// SerialStreamer over a scripted data port (uart_test::FakeDataPort): framing
// (magic word, header, exactly totalPacketLen), publishing, frame-number gap
// tracking and rejected frames. Only public API: the frame layout itself is
// covered by test_uart_parse.
#include "test_harness.hpp"
#include "uart_test_frames.hpp"

#include "SerialStreamer.hpp"

#include <chrono>
#include <memory>
#include <thread>

using namespace uart_test;
using clk = std::chrono::steady_clock;

namespace {

struct Rig {
    std::shared_ptr<FakeDataPort> port;
    SerialStreamer s;
    explicit Rig(const std::string& name, size_t max_read = static_cast<size_t>(-1),
                 const std::string& board = "IWR1843", int timeout_ms = 300)
        : port(std::make_shared<FakeDataPort>(max_read)) {
        SystemConfigReader sys(write_serial_config(name, TEST_TMP_DIR, board, timeout_ms));
        CHECK(sys.initialized);
        CHECK(s.initialize(sys, port));
    }
    // take without waiting
    bool take(std::vector<cpsl::radar::Point>& pts, uint32_t& fn, uint64_t* overwritten = nullptr) {
        clk::time_point at;
        uint64_t ow = 0;
        const bool ok = s.take_frame(pts, fn, at, ow, clk::now());
        if (overwritten) *overwritten = ow;
        return ok;
    }
};

}  // namespace

TEST_CASE(valid_frame_points_and_side_info) {
    Rig r("ss_valid");
    r.port->push(make_frame(7, {points_tlv(2, 1.0f), side_info_tlv(2)}));
    CHECK(r.s.process_next_message());
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    CHECK(r.take(pts, fn));
    CHECK_EQ(fn, 7u);
    CHECK_EQ(r.s.get_latest_frame_number(), 7u);
    CHECK_EQ(pts.size(), static_cast<size_t>(2));
    CHECK_EQ(pts[0].x, 1.0f);
    CHECK_EQ(pts[1].v, 8.0f);
    CHECK_NEAR(pts[0].snr_db, 10.0, 1e-4);
    CHECK_NEAR(pts[1].snr_db, 10.1, 1e-4);
    CHECK_NEAR(pts[1].noise_db, -2.0, 1e-4);
    CHECK(!r.take(pts, fn));  // each frame once
}

TEST_CASE(frame_is_published_without_waiting_for_the_next_magic_word) {
    // P8: the old reader framed on the NEXT frame's magic word, so a lone
    // frame was never delivered
    Rig r("ss_lone");
    r.port->push(make_frame(1, {points_tlv(1, 0.0f)}));
    const clk::time_point t0 = clk::now();
    CHECK(r.s.process_next_message());
    CHECK(clk::now() - t0 < std::chrono::milliseconds(100));
    CHECK_EQ(r.s.get_committed_frame_count(), 1u);
}

TEST_CASE(frame_without_tlvs_is_valid_and_empty) {
    Rig r("ss_empty");
    r.port->push(make_frame(1, {}));
    CHECK(r.s.process_next_message());
    std::vector<cpsl::radar::Point> pts(5);
    uint32_t fn = 0;
    CHECK(r.take(pts, fn));
    CHECK(pts.empty());
}

TEST_CASE(unknown_tlv_types_are_skipped) {
    Rig r("ss_unknown");
    Tlv range_profile{TLVCodes::RANGE_PROFILE, Bytes(16, 0xEE)};
    r.port->push(make_frame(1, {range_profile, points_tlv(1, 5.0f)}));
    CHECK(r.s.process_next_message());
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    CHECK(r.take(pts, fn));
    CHECK_EQ(pts.size(), static_cast<size_t>(1));
    CHECK_EQ(pts[0].x, 5.0f);
}

TEST_CASE(stale_points_cleared_when_next_frame_has_none) {
    Rig r("ss_stale");
    r.port->push(make_frame(1, {points_tlv(3, 0.0f), side_info_tlv(3)}));
    r.port->push(make_frame(2, {}));
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    CHECK(r.s.process_next_message());
    CHECK(r.take(pts, fn));
    CHECK_EQ(pts.size(), static_cast<size_t>(3));
    CHECK(r.s.process_next_message());
    CHECK(r.take(pts, fn));
    CHECK_EQ(fn, 2u);
    CHECK(pts.empty());
}

TEST_CASE(missed_frames_counted_from_frame_number_gaps) {
    Rig r("ss_gaps");
    for (uint32_t fn : {10u, 11u, 14u, 15u}) r.port->push(make_frame(fn, {}));
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_missed_frame_count(), 0u);  // first frame: nothing to compare
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_missed_frame_count(), 0u);
    CHECK(r.s.process_next_message());           // 12, 13 missed
    CHECK_EQ(r.s.get_missed_frame_count(), 2u);
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_missed_frame_count(), 2u);
}

TEST_CASE(frame_with_bad_tlv_publishes_nothing) {
    // valid header, broken TLV: the previous frame stays published, the bad
    // frame is not counted for frame-number gaps (7 follows 5: 6 missed)
    Rig r("ss_badtlv");
    FrameOpts three_tlvs;
    three_tlvs.num_tlvs = 3;
    r.port->push(make_frame(5, {points_tlv(2, 1.0f), side_info_tlv(2)}));
    r.port->push(make_frame(6, {points_tlv(1, 9.0f)}, three_tlvs));
    r.port->push(make_frame(7, {}));
    CHECK(r.s.process_next_message());
    CHECK(r.s.process_next_message());  // drops 6 (warning), publishes 7
    CHECK_EQ(r.s.get_rejected_frame_count(), 1u);
    CHECK_EQ(r.s.get_latest_frame_number(), 7u);
    CHECK_EQ(r.s.get_committed_frame_count(), 2u);
    CHECK_EQ(r.s.get_missed_frame_count(), 1u);
}

TEST_CASE(rejected_frame_number_is_never_reported_as_latest) {
    // core-02 known bug, fixed: a rejected frame's header was visible
    Rig r("ss_rejected_latest");
    Tlv odd{TLVCodes::DETECTED_POINTS, Bytes(20, 0x41)};  // not a multiple of 16
    r.port->push(make_frame(3, {}));
    r.port->push(make_frame(99, {odd}));
    CHECK(r.s.process_next_message());
    CHECK(!r.s.process_next_message());  // 99 dropped, then the timeout
    CHECK_EQ(r.s.get_latest_frame_number(), 3u);
    CHECK_EQ(r.s.get_rejected_frame_count(), 1u);
}

TEST_CASE(timeout_without_data_returns_false_and_is_not_an_io_error) {
    Rig r("ss_timeout", static_cast<size_t>(-1), "IWR1843", 150);
    const clk::time_point t0 = clk::now();
    CHECK(!r.s.process_next_message());
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(clk::now() - t0).count();
    CHECK(ms >= 140);
    CHECK(ms < 150 + 300);
    CHECK(!r.s.io_error());
}

TEST_CASE(port_error_sets_io_error) {
    Rig r("ss_eio");
    r.port->fail();
    CHECK(!r.s.process_next_message());
    CHECK(r.s.io_error());
}

TEST_MAIN()
