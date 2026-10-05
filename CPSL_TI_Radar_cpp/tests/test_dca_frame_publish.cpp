// DCA1000Handler frame publish ordering (audit (a) G2, directive core-11).
//
// The frame-ready flag must never be visible before the cube it announces:
// the handler converts a frame, then publishes cube + flag together under one
// lock. A test hook runs in that window (after convert, before publish). A
// polling consumer must never get the previous frame flagged as new, and
// never a cube mixing two frames.
//
// Regression pin for core-14: the frame queue that replaces "latest frame
// wins" must keep these cases passing.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "DCA1000Handler.hpp"

#include <atomic>
#include <chrono>
#include <thread>

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

    explicit Fixture(const std::string& name) {
        sys.initialize(dca_test::write_system_config(name, dca_test::tmp_dir(), false));
        const cpsl::radar::BoardDescriptor& b = sys.getBoard();
        radar.initialize(sys.getRadarConfigPath(), b.cfg_dialect.rx_mask_fields, b.cfg_dialect.frame_period_field);
        B = radar.get_bytes_per_frame();
    }
    void push_frame(uint64_t index, uint16_t tag) {
        for (const auto& p : dca_test::frame_packets(index, B, tag, seq))
            h.ingest_packet(p.data(), static_cast<int>(p.size()));
    }
};

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
    CHECK_EQ(cube_tag(f.h.get_latest_adc_cube()), 1);
    CHECK(!f.h.check_new_frame_available());

    // frame 1: a consumer polls inside the publish window
    int hook_calls = 0;
    bool flag_in_window = false;
    int stale_tag = 0;
    f.h.set_publish_hook([&] {
        hook_calls++;
        if (f.h.check_new_frame_available()) {
            flag_in_window = true;
            stale_tag = cube_tag(f.h.get_latest_adc_cube());  // what a consumer would take
        }
    });
    f.push_frame(1, 2);
    CHECK_EQ(hook_calls, 1);
    CHECK(!flag_in_window);
    CHECK_EQ(stale_tag, 0);
    // after publish: flag and the new cube, together
    CHECK(f.h.check_new_frame_available());
    CHECK_EQ(cube_tag(f.h.get_latest_adc_cube()), 2);
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
            int tag = cube_tag(f.h.get_latest_adc_cube());
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

TEST_MAIN()
