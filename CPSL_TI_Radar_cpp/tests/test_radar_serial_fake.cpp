// Radar with serial streaming over fake transports (directive core-16): a
// scripted CLI (FakeCli) and a scripted data port (uart_test::FakeDataPort)
// through Transports. No serial port is opened.
#include "test_harness.hpp"
#include "fake_transports.hpp"
#include "uart_test_frames.hpp"

#include "Radar.hpp"

#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <thread>

using namespace cpsl::radar;
using namespace uart_test;
using clk = std::chrono::steady_clock;
using std::chrono::milliseconds;

namespace {

struct Rig {
    std::shared_ptr<FakeCli> cli = std::make_shared<FakeCli>();
    std::shared_ptr<FakeDataPort> data = std::make_shared<FakeDataPort>();
    std::unique_ptr<Radar> radar;

    explicit Rig(const std::string& name, const std::string& board = "IWR1843") {
        Result<RadarConfig> cfg = RadarConfig::load(write_serial_config(name, TEST_TMP_DIR, board, 300));
        CHECK(static_cast<bool>(cfg));
        if (!cfg) {
            std::cerr << cfg.status.message << std::endl;
            return;
        }
        Transports t;
        t.cli = cli;
        t.data = data;
        auto r = Radar::open(*cfg, t);
        CHECK(static_cast<bool>(r));
        if (r) radar = std::move(*r);
        else std::cerr << r.status.message << std::endl;
    }
    bool start() { return radar && static_cast<bool>(radar->configure()) && static_cast<bool>(radar->start()); }
};

long long ms_since(clk::time_point t0) {
    return std::chrono::duration_cast<milliseconds>(clk::now() - t0).count();
}

}  // namespace

TEST_CASE(point_clouds_arrive_through_next_point_cloud) {
    Rig rig("rs_basic");
    CHECK(rig.start());
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    PointCloud pc;
    Status why;
    CHECK(!r.next_point_cloud(pc, milliseconds(20), &why));
    CHECK(why.code == Code::timeout);

    const clk::time_point t0 = clk::now();
    rig.data->push(make_frame(1, {points_tlv(2, 1.0f), side_info_tlv(2)}));
    CHECK(r.next_point_cloud(pc, milliseconds(1000), &why));
    CHECK(static_cast<bool>(why));
    CHECK(ms_since(t0) < 200);  // as soon as it is read, no next magic word needed
    CHECK_EQ(pc.frame_number, 1u);
    CHECK(pc.completed_at >= t0);
    CHECK_EQ(pc.points.size(), static_cast<size_t>(2));
    CHECK_EQ(pc.points[1].x, 5.0f);
    CHECK_NEAR(pc.points[1].snr_db, 10.1, 1e-4);

    rig.data->push(make_frame(2, {}));
    CHECK(r.next_point_cloud(pc, milliseconds(1000)));
    CHECK_EQ(pc.frame_number, 2u);
    CHECK(pc.points.empty());
    const Stats s = r.stats();
    CHECK_EQ(s.serial_frames, 2u);
    CHECK_EQ(s.serial_missed, 0u);
    CHECK(static_cast<bool>(r.stop()));
}

TEST_CASE(stop_wakes_a_consumer_blocked_in_next_point_cloud) {
    Rig rig("rs_stopwake");
    CHECK(rig.start());
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    Status why;
    long long woke_ms = -1;
    clk::time_point stop_at;
    std::thread consumer([&] {
        PointCloud pc;
        r.next_point_cloud(pc, milliseconds(10000), &why);
        woke_ms = ms_since(stop_at);
    });
    std::this_thread::sleep_for(milliseconds(100));
    stop_at = clk::now();
    r.stop();
    consumer.join();
    CHECK(why.code == Code::stopped);
    CHECK(woke_ms >= 0 && woke_ms < 1000);
}

TEST_CASE(data_port_error_ends_the_stream_with_io_error) {
    Rig rig("rs_eio");
    CHECK(rig.start());
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    WarnCapture warns;
    rig.data->fail();
    PointCloud pc;
    Status why;
    const clk::time_point t0 = clk::now();
    CHECK(!r.next_point_cloud(pc, milliseconds(3000), &why));
    CHECK(why.code == Code::io_error);
    CHECK(ms_since(t0) < 1000);  // woken, not the 3 s timeout
    CHECK(static_cast<bool>(r.stop()));
}

TEST_CASE(frames_replaced_before_they_are_taken_count_as_overwritten) {
    Rig rig("rs_overwritten");
    CHECK(rig.start());
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    for (uint32_t k = 1; k <= 3; k++) rig.data->push(make_frame(k, {}));
    std::this_thread::sleep_for(milliseconds(150));
    PointCloud pc;
    CHECK(r.next_point_cloud(pc, milliseconds(1000)));
    CHECK_EQ(pc.frame_number, 3u);
    CHECK_EQ(r.stats().serial_overwritten, 2u);
    r.stop();
}

TEST_MAIN()
