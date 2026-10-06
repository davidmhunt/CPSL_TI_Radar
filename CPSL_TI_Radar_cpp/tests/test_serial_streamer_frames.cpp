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

// ---- framing ----

TEST_CASE(garbage_before_the_magic_word_is_skipped) {
    Rig r("ss_garbage");
    Bytes junk(100, 0x55);
    junk.insert(junk.end(), {0x02, 0x01, 0x04, 0x03, 0x06});  // a cut-off magic word
    r.port->push(cat({junk, make_frame(4, {points_tlv(1, 3.0f)})}));
    CHECK(r.s.process_next_message());
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    CHECK(r.take(pts, fn));
    CHECK_EQ(fn, 4u);
    CHECK_EQ(pts.size(), static_cast<size_t>(1));
    CHECK_EQ(r.s.get_rejected_frame_count(), 0u);
}

TEST_CASE(two_frames_back_to_back_in_one_chunk) {
    Rig r("ss_b2b");
    const Bytes a = make_frame(1, {points_tlv(1, 1.0f)});
    const Bytes b = make_frame(2, {points_tlv(2, 2.0f)});
    r.port->push(cat({a, b}));
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    CHECK(r.s.process_next_message());
    CHECK(r.take(pts, fn));
    CHECK_EQ(fn, 1u);
    CHECK(r.s.process_next_message());
    CHECK(r.take(pts, fn));
    CHECK_EQ(fn, 2u);
    CHECK_EQ(pts.size(), static_cast<size_t>(2));
    // reads never ask for more than the rest of the current frame
    CHECK(r.port->max_cap() <= std::max(a.size(), b.size()));
}

TEST_CASE(frame_arriving_one_byte_per_read) {
    Rig r("ss_bytewise", 1);
    const Bytes f = make_frame(8, {points_tlv(3, 0.0f), side_info_tlv(3)});
    r.port->push(cat({Bytes(5, 0xAB), f}));
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_latest_frame_number(), 8u);
    CHECK(r.port->reads() >= f.size());
}

TEST_CASE(partial_frame_survives_a_timeout) {
    Rig r("ss_partial", static_cast<size_t>(-1), "IWR1843", 100);
    const Bytes f = make_frame(2, {points_tlv(4, 0.0f)});
    r.port->push(Bytes(f.begin(), f.begin() + 50));
    CHECK(!r.s.process_next_message());  // times out mid-frame
    CHECK(!r.s.io_error());
    r.port->push(Bytes(f.begin() + 50, f.end()));
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_latest_frame_number(), 2u);
}

TEST_CASE(impossible_total_length_resynchronizes) {
    // a magic word followed by a bogus header (e.g. inside a corrupted
    // frame): totalPacketLen 0xFFFFFFF0 is dropped, the next frame is found
    Rig r("ss_resync");
    Bytes bogus = make_frame(77, {});
    bogus[12] = 0xF0;
    bogus[13] = bogus[14] = bogus[15] = 0xFF;
    r.port->push(cat({bogus, make_frame(5, {points_tlv(1, 0.0f)})}));
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_latest_frame_number(), 5u);
    CHECK_EQ(r.s.get_rejected_frame_count(), 1u);
}

TEST_CASE(overstated_length_drops_the_frame_and_finds_the_next) {
    // a corrupt frame whose totalPacketLen is 32 bytes too long swallows the
    // start of the next frame; after the rejection the search restarts just
    // past its magic word, so the next frame is still found
    Rig r("ss_overstated");
    FrameOpts longer;
    longer.total_delta = 32;
    Tlv odd{TLVCodes::DETECTED_POINTS, Bytes(20, 0)};
    r.port->push(cat({make_frame(1, {odd}, longer), make_frame(2, {}), make_frame(3, {})}));
    CHECK(r.s.process_next_message());
    CHECK_EQ(r.s.get_latest_frame_number(), 2u);
    CHECK_EQ(r.s.get_rejected_frame_count(), 1u);
}

TEST_CASE(close_ends_a_read_in_progress) {
    Rig r("ss_close", static_cast<size_t>(-1), "IWR1843", 5000);
    std::thread t([&r] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        r.s.close();
    });
    const clk::time_point t0 = clk::now();
    CHECK(!r.s.process_next_message());
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(clk::now() - t0).count();
    t.join();
    CHECK(ms < 400);  // not the 5 s timeout
    CHECK(!r.s.io_error());
}

TEST_CASE(take_frame_waits_for_a_publish_and_close_wakes_it) {
    Rig r("ss_wait", static_cast<size_t>(-1), "IWR1843", 2000);
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    clk::time_point at;
    uint64_t ow = 0;
    std::thread reader([&r] { r.s.process_next_message(); });
    std::thread writer([&r] {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        r.port->push(make_frame(12, {points_tlv(1, 0.0f)}));
    });
    const clk::time_point t0 = clk::now();
    CHECK(r.s.take_frame(pts, fn, at, ow, t0 + std::chrono::seconds(2)));
    CHECK(clk::now() - t0 < std::chrono::milliseconds(500));
    CHECK_EQ(fn, 12u);
    CHECK(at >= t0);
    reader.join();
    writer.join();
    std::thread closer([&r] {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        r.s.close();
    });
    const clk::time_point t1 = clk::now();
    CHECK(!r.s.take_frame(pts, fn, at, ow, t1 + std::chrono::seconds(5)));
    CHECK(clk::now() - t1 < std::chrono::milliseconds(1000));
    closer.join();
}

TEST_CASE(overwritten_frames_are_counted) {
    Rig r("ss_overwritten");
    for (uint32_t fn = 1; fn <= 3; fn++) r.port->push(make_frame(fn, {}));
    for (int i = 0; i < 3; i++) CHECK(r.s.process_next_message());
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    uint64_t ow = 0;
    CHECK(r.take(pts, fn, &ow));
    CHECK_EQ(fn, 3u);
    CHECK_EQ(ow, 2u);
}

TEST_CASE(point_buffers_are_reused) {
    // reader work buffer, published buffer and the consumer's: at most 3
    // distinct allocations over many frames once they have grown
    Rig r("ss_reuse");
    std::vector<cpsl::radar::Point> pts;
    uint32_t fn = 0;
    std::vector<const cpsl::radar::Point*> seen;
    for (uint32_t k = 1; k <= 30; k++) {
        const int n = k <= 3 ? 10 : static_cast<int>(10 - k % 3);  // all three buffers grow first
        r.port->push(make_frame(k, {points_tlv(n, 0.0f)}));
        CHECK(r.s.process_next_message());
        CHECK(r.take(pts, fn));
        if (k > 3 && std::find(seen.begin(), seen.end(), pts.data()) == seen.end()) seen.push_back(pts.data());
    }
    CHECK(seen.size() <= 3u);
}

TEST_MAIN()
