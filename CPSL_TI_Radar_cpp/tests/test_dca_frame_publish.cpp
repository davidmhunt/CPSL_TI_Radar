// DCA1000Handler frame publish ordering (audit (a) G2, directive core-11) and
// the frame queue (core-14 P2, P7).
//
// A frame must never be visible before the cube it announces: the handler
// converts a frame, then puts the cube in the queue under one lock. A test
// hook runs in that window (after convert, before publish). A consumer must
// never get the previous frame again, and never a cube mixing two frames.
// core-11 pinned this for "latest frame wins"; since core-14 the same cases
// run against the drop-oldest queue (depth runtime.frame_queue_depth, default
// 4), plus the queue's own rules: drop-oldest counting, in-order delivery,
// and a blocked consumer woken only after its frame is in the queue.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "DCA1000Handler.hpp"

#include <algorithm>
#include <atomic>
#include <fstream>
#include <chrono>
#include <string>
#include <thread>
#include <vector>

#include "Log.hpp"

typedef std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> Cube;

// the frame's tag if every sample is (tag, tag), -1 for an empty or mixed cube
static int cube_tag(const Cube& c) {
    int tag = -1;
    for (const auto& rx : c)
        for (const auto& s : rx)
            for (const std::complex<std::int16_t>& v : s) {
                if (v.real() != v.imag()) return -1;
                if (tag == -1) tag = v.real();
                else if (tag != v.real()) return -1;
            }
    return tag;
}

struct Fixture {
    SystemConfigReader sys;
    RadarConfigReader radar;
    DCA1000Handler h;
    size_t B = 0;
    uint32_t seq = 1;

    // queue_depth 0: the default (runtime.frame_queue_depth unset)
    explicit Fixture(const std::string& name, int queue_depth = 0) {
        const std::string path = dca_test::write_system_config(name, dca_test::tmp_dir(), false);
        if (queue_depth > 0) {
            nlohmann::json j;
            {
                std::ifstream in(path);
                j = nlohmann::json::parse(in);
            }
            j["runtime"] = {{"frame_queue_depth", queue_depth}};
            std::ofstream(path) << j.dump(2);
        }
        sys.initialize(path);
        const cpsl::radar::BoardDescriptor& b = sys.getBoard();
        radar.initialize(sys.getRadarConfigPath(), b.cfg_dialect.rx_mask_fields, b.cfg_dialect.frame_period_field);
        B = radar.get_bytes_per_frame();
    }
    void push_frame(uint64_t index, uint16_t tag) {
        for (const auto& p : dca_test::frame_packets(index, B, tag, seq))
            h.ingest_packet(p.data(), static_cast<int>(p.size()));
    }
};

// the tag of the oldest queued frame, taken without waiting; -2 if none
static int take_tag(DCA1000Handler& h, uint64_t* index = nullptr) {
    Cube c;
    uint64_t i = 0;
    size_t missing = 0;
    std::chrono::steady_clock::time_point at;
    if (!h.take_frame(c, i, missing, at)) return -2;
    if (index) *index = i;
    return cube_tag(c);
}

TEST_CASE(fixture_is_hardware_free_and_configured) {
    Fixture f("publish_fixture");
    CHECK(f.sys.initialized);
    CHECK(f.radar.initialized);
    CHECK_EQ(f.B, static_cast<size_t>(231840));
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    CHECK(f.h.packet_source() == nullptr);  // no socket, no DCA1000
    CHECK(!f.h.check_new_frame_available());
}

TEST_CASE(flag_is_not_visible_between_convert_and_publish) {
    Fixture f("publish_hook");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));

    f.push_frame(0, 1);
    CHECK(f.h.check_new_frame_available());
    CHECK_EQ(take_tag(f.h), 1);
    CHECK(!f.h.check_new_frame_available());

    // frame 1: a consumer polls inside the publish window
    int hook_calls = 0;
    bool flag_in_window = false;
    int stale_tag = 0;
    f.h.set_publish_hook([&] {
        hook_calls++;
        if (f.h.check_new_frame_available()) {
            flag_in_window = true;
            stale_tag = take_tag(f.h);  // what a consumer would take
        }
    });
    f.push_frame(1, 2);
    CHECK_EQ(hook_calls, 1);
    CHECK(!flag_in_window);
    CHECK_EQ(stale_tag, 0);
    // after publish: flag and the new cube, together
    CHECK(f.h.check_new_frame_available());
    CHECK_EQ(take_tag(f.h), 2);
    CHECK(!f.h.check_new_frame_available());
}

TEST_CASE(polling_consumer_never_gets_a_stale_or_torn_frame) {
    Fixture f("publish_race");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    // widen the window between convert and publish
    f.h.set_publish_hook([] { std::this_thread::sleep_for(std::chrono::microseconds(300)); });

    const int frames = 40;
    std::atomic<bool> done{false};
    std::thread producer([&] {
        for (int k = 0; k < frames; k++) {
            f.push_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
            std::this_thread::sleep_for(std::chrono::microseconds(200));
        }
        done = true;
    });

    int last = 0, received = 0, stale = 0, torn = 0;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
    while (std::chrono::steady_clock::now() < deadline) {
        if (f.h.check_new_frame_available()) {
            int tag = take_tag(f.h);
            if (tag < 0) torn++;
            else if (tag <= last) stale++;  // previous frame delivered as new
            else last = tag;
            received++;
            if (last == frames) break;
        } else if (done && !f.h.check_new_frame_available()) {
            break;
        }
    }
    producer.join();
    std::cout << "    consumer received " << received << " frames, last tag " << last << std::endl;
    CHECK_EQ(stale, 0);
    CHECK_EQ(torn, 0);
    CHECK_EQ(last, frames);
    CHECK(received > 1);
}

TEST_CASE(default_queue_holds_four_frames_and_drops_the_oldest) {
    Fixture f("queue_default");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    for (int k = 0; k < 6; k++) f.push_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
    CHECK_EQ(f.h.queued_frames(), size_t(4));
    CHECK_EQ(f.h.get_stats().frames_overwritten, uint64_t(2));  // frames 0 and 1
    uint64_t index = 0;
    for (int k = 2; k < 6; k++) {
        CHECK_EQ(take_tag(f.h, &index), k + 1);
        CHECK_EQ(index, static_cast<uint64_t>(k));
    }
    CHECK_EQ(take_tag(f.h), -2);
    CHECK_EQ(f.h.get_stats().frames, uint64_t(6));
}

TEST_CASE(depth_one_is_latest_wins) {
    Fixture f("queue_depth1", 1);
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    for (int k = 0; k < 3; k++) f.push_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
    CHECK_EQ(f.h.queued_frames(), size_t(1));
    CHECK_EQ(f.h.get_stats().frames_overwritten, uint64_t(2));
    CHECK_EQ(take_tag(f.h), 3);
    f.push_frame(3, 4);  // taken in time: nothing dropped
    CHECK_EQ(take_tag(f.h), 4);
    CHECK_EQ(f.h.get_stats().frames_overwritten, uint64_t(2));
}

TEST_CASE(blocked_consumer_is_woken_after_its_frame_is_queued) {
    // The consumer waits on the condition variable. The producer notifies only
    // after the frame is in the queue; a notify sent earlier (before the
    // publish hook, i.e. before the buffer swap) would find the queue empty,
    // the consumer would wait again and miss the frame until its 3 s
    // deadline. The hook widens that window to 2 ms.
    Fixture f("queue_wake", 2);
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    f.h.set_publish_hook([] { std::this_thread::sleep_for(std::chrono::milliseconds(2)); });
    const int frames = 15;
    std::atomic<int> acked{-1};
    std::atomic<int> bad{0};
    std::thread consumer([&] {
        Cube c;
        for (int k = 0; k < frames; k++) {
            uint64_t index = 0;
            size_t missing = 0;
            std::chrono::steady_clock::time_point at;
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
            if (!f.h.take_frame(c, index, missing, at, deadline)) return;  // timed out: acked stays behind
            if (index != static_cast<uint64_t>(k) || cube_tag(c) != k + 1) bad++;
            acked = k;
        }
    });
    int late = 0;
    long long worst_us = 0;
    for (int k = 0; k < frames; k++) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));  // the consumer is waiting by now
        const auto t0 = std::chrono::steady_clock::now();
        f.push_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
        while (acked.load() < k && std::chrono::steady_clock::now() - t0 < std::chrono::milliseconds(500)) {
            std::this_thread::yield();
        }
        const long long us =
            std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
        worst_us = std::max(worst_us, us);
        if (acked.load() < k) late++;
    }
    consumer.join();
    std::cout << "    worst push -> consumer ack: " << worst_us << " us" << std::endl;
    CHECK_EQ(late, 0);
    CHECK_EQ(bad.load(), 0);
    CHECK_EQ(acked.load(), frames - 1);
    CHECK_EQ(f.h.get_stats().frames_overwritten, uint64_t(0));
}

TEST_CASE(close_frames_wakes_a_blocked_consumer) {
    Fixture f("queue_close");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    bool got = true;
    long long waited_ms = -1;
    std::thread consumer([&] {
        Cube c;
        uint64_t index = 0;
        size_t missing = 0;
        std::chrono::steady_clock::time_point at;
        const auto t0 = std::chrono::steady_clock::now();
        got = f.h.take_frame(c, index, missing, at, t0 + std::chrono::seconds(10));
        waited_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    f.h.close_frames();
    consumer.join();
    CHECK(!got);
    CHECK(waited_ms >= 40 && waited_ms < 2000);
    f.push_frame(0, 1);  // after close: queued, but take_frame returns false at once
    CHECK_EQ(take_tag(f.h), -2);
}

TEST_CASE(frames_are_swapped_through_a_pool_not_copied) {
    // design P2: a consumer that keeps reusing one Cube sees only the pool's
    // few buffers come back (swapped, never copied or reallocated)
    Fixture f("publish_pool");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    Cube out;  // empty: it joins the pool on the first take and is reshaped once
    std::vector<const void*> seen;
    for (int k = 0; k < 12; k++) {
        f.push_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
        uint64_t index = 0;
        size_t missing = 0;
        std::chrono::steady_clock::time_point at;
        CHECK(f.h.take_frame(out, index, missing, at));
        CHECK_EQ(index, static_cast<uint64_t>(k));
        CHECK_EQ(cube_tag(out), k + 1);
        const void* p = out.empty() || out[0].empty() ? nullptr : out[0][0].data();
        if (std::find(seen.begin(), seen.end(), p) == seen.end()) seen.push_back(p);
    }
    // the work buffer, the queue's 4 slots and the consumer's own buffer
    std::cout << "    distinct buffers seen by the consumer: " << seen.size() << std::endl;
    CHECK(seen.size() <= 6);
}

TEST_CASE(debug_status_is_periodic_not_per_frame_or_per_packet) {
    // design P10: at debug level a drop storm must not log per packet or per
    // frame; one counter line per DCA1000Handler::kStatusPeriod at most
    Fixture f("publish_quiet");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    std::vector<std::string> lines;
    cpsl::radar::set_log_level(cpsl::radar::LogLevel::debug);
    cpsl::radar::set_log_sink([&](cpsl::radar::LogLevel, const std::string& m) { lines.push_back(m); });
    const int frames = 6;
    for (int k = 0; k < frames; k++) {
        auto p = dca_test::frame_packets(static_cast<uint64_t>(k), f.B, static_cast<uint16_t>(k + 1), f.seq);
        for (size_t i = 0; i < p.size(); i++) {
            if (i % 20 == 5) continue;  // a dropped packet every 20
            f.h.ingest_packet(p[i].data(), static_cast<int>(p[i].size()));
        }
    }
    cpsl::radar::set_log_sink(nullptr);
    cpsl::radar::set_log_level(cpsl::radar::LogLevel::info);
    CHECK(f.h.get_stats().frames >= static_cast<uint64_t>(frames - 1));
    CHECK(f.h.get_stats().assembler.dropped_packet_events > 30);
    CHECK_EQ(lines.size(), size_t(1));  // the first frame's line only (the frames take well under 1 s)
    if (!lines.empty()) {
        CHECK(lines[0].find("DCA1000: frames 1, packets ") == 0);
    }
}

TEST_CASE(dca1000_restart_resyncs_with_one_warning) {
    // core-15 (core-11 review S1): a DCA1000 restart mid-capture sends byte
    // counts and sequence numbers from 0 / 1 again. The handler warns once,
    // and the new stream's frames are published with increasing indices.
    Fixture f("publish_restart");
    CHECK(f.h.configure_pipeline(f.sys, f.radar));
    std::vector<std::string> warns;
    cpsl::radar::set_log_sink([&](cpsl::radar::LogLevel l, const std::string& m) {
        if (l == cpsl::radar::LogLevel::warn) warns.push_back(m);
    });
    for (uint64_t k = 0; k < 4; k++) f.push_frame(k, static_cast<uint16_t>(k + 1));
    std::vector<int> tags;
    std::vector<uint64_t> idx;
    uint64_t i = 0;
    for (int t; (t = take_tag(f.h, &i)) != -2;) { tags.push_back(t); idx.push_back(i); }
    f.seq = 1;  // the restart
    for (uint64_t k = 0; k < 3; k++) f.push_frame(k, static_cast<uint16_t>(k + 11));
    for (int t; (t = take_tag(f.h, &i)) != -2;) { tags.push_back(t); idx.push_back(i); }
    cpsl::radar::set_log_sink(nullptr);
    const std::vector<int> want = {1, 2, 3, 4, 11, 12, 13};
    CHECK(tags == want);
    for (size_t k = 1; k < idx.size(); k++) CHECK(idx[k] > idx[k - 1]);
    CHECK_EQ(f.h.get_stats().assembler.resyncs, 1u);
    CHECK_EQ(warns.size(), size_t(1));
    if (!warns.empty()) CHECK(warns[0].find("resynchronised") != std::string::npos);
}

TEST_MAIN()
