// cpsl::radar::Radar end to end over fake transports (driver v2 design §6,
// directive core-13 Step 5): a ReplayPacketSource stands in for the DCA1000
// and a scripted FakeCli for the radar's CLI port. Nothing is opened but
// files under the test's build directory.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "fake_transports.hpp"
#include "Radar.hpp"

#include <sched.h>
#include <sys/stat.h>

#include <atomic>
#include <mutex>
#include <filesystem>
#include <stdexcept>
#include <fstream>
#include <thread>

using cpsl::radar::AdcFrame;
using cpsl::radar::Code;
using cpsl::radar::Radar;
using cpsl::radar::RadarConfig;
using cpsl::radar::ReplayPacketSource;
using cpsl::radar::Status;
using std::chrono::milliseconds;
using clk = std::chrono::steady_clock;

namespace {

const std::string kRoot = dca_test::tmp_dir() + "/radar_e2e";

const bool kSetup = [] {
    std::filesystem::remove_all(kRoot);
    std::filesystem::create_directories(kRoot);
    return true;
}();

// A system config for tests/data/radar/iwr1843.cfg (231840 B/frame, 100 ms
// frames, cmd_timeout_ms 100) with the DCA1000 enabled; `edit` changes it.
template <class Edit>
RadarConfig load(const std::string& name, Edit edit) {
    const std::string out = kRoot + "/" + name;
    std::filesystem::create_directories(out);
    json j;
    {
        std::ifstream f(dca_test::write_system_config(name, out, true));
        j = json::parse(f);
    }
    edit(j);
    const std::string path = kRoot + "/" + name + ".json";
    std::ofstream(path) << j.dump(2);
    auto r = RadarConfig::load(path);
    CHECK(static_cast<bool>(r));
    if (!r) std::cerr << r.status.message << std::endl;
    return *r;
}
RadarConfig load(const std::string& name) {
    return load(name, [](json&) {});
}

struct Rig {
    std::shared_ptr<FakeCli> cli = std::make_shared<FakeCli>();
    std::shared_ptr<ReplayPacketSource> packets = std::make_shared<ReplayPacketSource>();
    std::unique_ptr<Radar> radar;
    uint32_t seq = 1;
    size_t bytes_per_frame = 0;

    explicit Rig(const RadarConfig& cfg) {
        bytes_per_frame = static_cast<size_t>(cfg.frame_shape().bytes);
        auto r = Radar::open(cfg, {cli, packets});
        CHECK(static_cast<bool>(r));
        if (r) radar = std::move(*r);
        else std::cerr << r.status.message << std::endl;
    }
    // queue frame `index` (every 16-bit word = tag); `drop` removes that packet
    void send_frame(uint64_t index, uint16_t tag, int drop = -1) {
        auto p = dca_test::frame_packets(index, bytes_per_frame, tag, seq);
        for (int i = 0; i < static_cast<int>(p.size()); i++) {
            if (i != drop) packets->push(p[i]);
        }
    }
};

bool all_samples_are(const AdcFrame& f, int16_t v) {
    for (const auto& rx : f.data)
        for (const auto& s : rx)
            for (const auto& c : s)
                if (c.real() != v || c.imag() != v) return false;
    return true;
}

long long ms_since(clk::time_point t0) {
    return std::chrono::duration_cast<milliseconds>(clk::now() - t0).count();
}

}  // namespace

TEST_CASE(configure_start_stop_idempotence) {
    Rig rig(load("idem"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(r.start().code == Code::invalid_state);  // before configure()
    CHECK(static_cast<bool>(r.configure()));
    CHECK(rig.cli->writes() > 5);  // the cfg went through the fake CLI
    CHECK(static_cast<bool>(r.start()));
    CHECK(static_cast<bool>(r.start()));  // idempotent while running
    CHECK_EQ(rig.cli->count("sensorStart\n"), size_t(1));
    CHECK(r.configure().code == Code::invalid_state);  // not while running
    const Status s1 = r.stop();
    const Status s2 = r.stop();
    CHECK(static_cast<bool>(s1));
    CHECK(s1 == s2);
    CHECK_EQ(rig.cli->count("sensorStop\n"), size_t(2));  // one in the cfg, one from stop()
    CHECK(r.start().code == Code::invalid_state);  // after stop()
    CHECK(r.configure().code == Code::invalid_state);
    AdcFrame f;
    Status why;
    CHECK(!r.next_adc_frame(f, milliseconds(10), &why));
    CHECK(why.code == Code::stopped);
    cpsl::radar::PointCloud pc;
    CHECK(!r.next_point_cloud(pc, milliseconds(10), &why));
    CHECK(why.code == Code::disabled);
}

TEST_CASE(golden_frames_through_next_adc_frame) {
    Rig rig(load("golden"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    AdcFrame f;
    Status why;
    auto check_frame = [&](uint64_t index, uint32_t missing, int16_t value) {
        CHECK(r.next_adc_frame(f, milliseconds(3000), &why));
        CHECK_EQ(f.index, index);
        CHECK_EQ(f.missing_bytes, missing);
        CHECK_EQ(f.data.size(), size_t(4));          // [rx]
        CHECK_EQ(f.data[0].size(), size_t(63));      // [sample]
        CHECK_EQ(f.data[0][0].size(), size_t(230));  // [chirp]
        CHECK_EQ(f.shape.bytes, static_cast<uint64_t>(rig.bytes_per_frame));
        if (missing == 0) CHECK(all_samples_are(f, value));
    };
    // a complete frame is published as soon as its last byte lands
    rig.send_frame(0, 100);
    check_frame(0, 0, 100);
    rig.send_frame(1, 101);
    check_frame(1, 0, 101);
    // frame 2 loses one packet: it is published (zero-filled) only once the
    // stream is the reorder slack (8 packets) past its end
    rig.send_frame(2, 102, 7);
    CHECK(!r.next_adc_frame(f, milliseconds(200), &why));
    CHECK(why.code == Code::timeout);
    auto p3 = dca_test::frame_packets(3, rig.bytes_per_frame, 103, rig.seq);
    for (size_t i = 0; i < 12; i++) rig.packets->push(p3[i]);
    check_frame(2, 1462, 0);
    for (size_t i = 12; i < p3.size(); i++) rig.packets->push(p3[i]);
    check_frame(3, 0, 103);
    CHECK(static_cast<bool>(r.stop()));
    const cpsl::radar::Stats st = r.stats();
    CHECK_EQ(st.frames, uint64_t(4));
    CHECK_EQ(st.dropped, uint64_t(1));
    CHECK_EQ(st.incomplete_frames, uint64_t(1));
    CHECK_EQ(st.frames_overwritten, uint64_t(0));
    CHECK_EQ(st.packets, static_cast<uint64_t>(rig.seq - 1));
    // adc_data.bin holds the four frames, flushed and closed
    struct stat sb;
    CHECK(stat((kRoot + "/golden/adc_data.bin").c_str(), &sb) == 0);
    CHECK_EQ(static_cast<uint64_t>(sb.st_size), 4 * static_cast<uint64_t>(rig.bytes_per_frame));
}

TEST_CASE(frame_queue_drops_the_oldest_and_counts_it) {
    // default runtime.frame_queue_depth 4: 6 frames with nobody waiting keep
    // the newest 4, in order; the 2 oldest are counted as overwritten
    Rig rig(load("overwrite"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    for (int k = 0; k < 6; k++) rig.send_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
    const clk::time_point t0 = clk::now();
    while (r.stats().frames < 6 && ms_since(t0) < 3000) std::this_thread::sleep_for(milliseconds(5));
    CHECK_EQ(r.stats().frames_overwritten, uint64_t(2));
    AdcFrame f;
    for (int k = 2; k < 6; k++) {
        CHECK(r.next_adc_frame(f, milliseconds(1000)));
        CHECK_EQ(f.index, static_cast<uint64_t>(k));
        CHECK(all_samples_are(f, static_cast<int16_t>(k + 1)));
    }
    Status why;
    CHECK(!r.next_adc_frame(f, milliseconds(50), &why));
    CHECK(why.code == Code::timeout);
    r.stop();
}

TEST_CASE(frame_queue_depth_one_is_latest_wins) {
    Rig rig(load("overwrite1", [](json& j) { j["runtime"] = {{"frame_queue_depth", 1}}; }));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    for (int k = 0; k < 4; k++) rig.send_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
    const clk::time_point t0 = clk::now();
    while (r.stats().frames < 4 && ms_since(t0) < 3000) std::this_thread::sleep_for(milliseconds(5));
    AdcFrame f;
    CHECK(r.next_adc_frame(f, milliseconds(1000)));
    CHECK_EQ(f.index, uint64_t(3));  // the latest
    CHECK_EQ(r.stats().frames_overwritten, uint64_t(3));
    r.stop();
}

// Publish ordering through the queue (core-14 P7): a consumer racing the
// producer never sees a stale, duplicate or torn frame, indices strictly
// increase, and every frame it did not get was counted in frames_overwritten.
static void race(const std::string& name, int depth, int frames) {
    Rig rig(load(name, [depth](json& j) { j["runtime"] = {{"frame_queue_depth", depth}}; }));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    std::vector<uint64_t> got;
    int bad = 0;
    std::atomic<bool> produced{false};
    std::thread consumer([&] {
        AdcFrame f;
        uint32_t rnd = 12345;
        for (;;) {
            Status why;
            if (r.next_adc_frame(f, milliseconds(produced ? 300 : 3000), &why)) {
                if (!got.empty() && f.index <= got.back()) bad++;  // stale or duplicate
                if (!all_samples_are(f, static_cast<int16_t>(f.index + 1))) bad++;  // torn or wrong buffer
                got.push_back(f.index);
                rnd = rnd * 1103515245u + 12345u;
                std::this_thread::sleep_for(std::chrono::microseconds((rnd >> 16) % 3000));  // a slow, uneven consumer
            } else if (produced) {
                break;  // drained
            }
        }
    });
    for (int k = 0; k < frames; k++) {
        rig.send_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
        std::this_thread::sleep_for(std::chrono::microseconds(k % 3 == 0 ? 1500 : 200));
    }
    const clk::time_point t0 = clk::now();
    while (r.stats().frames < static_cast<uint64_t>(frames) && ms_since(t0) < 10000)
        std::this_thread::sleep_for(milliseconds(2));
    produced = true;
    consumer.join();
    const cpsl::radar::Stats st = r.stats();
    uint64_t gaps = 0;
    for (size_t i = 0; i < got.size(); i++) gaps += got[i] - (i == 0 ? 0 : got[i - 1] + 1);
    if (!got.empty()) gaps += static_cast<uint64_t>(frames - 1) - got.back();
    std::cout << "    depth " << depth << ": received " << got.size() << " of " << frames << ", overwritten "
              << st.frames_overwritten << std::endl;
    CHECK_EQ(bad, 0);
    CHECK_EQ(st.frames, static_cast<uint64_t>(frames));
    CHECK(!got.empty());
    CHECK_EQ(st.frames_overwritten, gaps);
    CHECK_EQ(st.frames_overwritten + got.size(), static_cast<uint64_t>(frames));
    r.stop();
}

TEST_CASE(publish_ordering_consumer_racing_the_producer) {
    race("race_d1", 1, 60);
    race("race_d2", 2, 60);
    race("race_d4", 4, 60);
}

TEST_CASE(concurrent_stop_waits_for_the_first_and_shares_its_status) {
    Rig rig(load("concurrent"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    // sensorStop's write hangs for the whole stop window (300 ms), then fails
    rig.cli->fail_from_now(FakeCli::Fail::write_hangs);
    Status a, b;
    long long ta = 0, tb = 0;
    const clk::time_point t0 = clk::now();
    std::thread t1([&] { a = r.stop(); ta = ms_since(t0); });
    std::thread t2([&] { b = r.stop(); tb = ms_since(t0); });
    t1.join();
    t2.join();
    CHECK(a.code == Code::io_error);
    CHECK(a == b);
    CHECK(ta >= 290);  // neither caller returned before the stop had finished
    CHECK(tb >= 290);
    CHECK_EQ(rig.cli->count("sensorStop\n"), size_t(2));  // cfg + one stop
}

// core-13 review S1: destroying a running Radar stops it (sensorStop sent,
// threads joined) without an explicit stop()
TEST_CASE(destructor_stops_a_running_radar) {
    Rig rig(load("dtor"));
    if (!rig.radar) return;
    CHECK(static_cast<bool>(rig.radar->configure()));
    CHECK(static_cast<bool>(rig.radar->start()));
    rig.send_frame(0, 1);
    const clk::time_point t0 = clk::now();
    while (rig.radar->stats().frames < 1 && ms_since(t0) < 3000) std::this_thread::sleep_for(milliseconds(5));
    rig.radar.reset();
    CHECK_EQ(rig.cli->count("sensorStop\n"), size_t(2));  // one in the cfg, one from the destructor
    CHECK(!rig.packets->started());                        // the packet source was stopped
}

// core-13 review S1: a consumer blocked in next_adc_frame (on the frame
// queue's condition variable) returns Code::stopped as soon as stop() runs,
// not at the end of its timeout
TEST_CASE(stop_wakes_a_consumer_blocked_in_next_adc_frame) {
    Rig rig(load("wake_on_stop"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    Status why;
    bool got = true;
    long long waited = -1;
    clk::time_point returned_at;
    std::thread consumer([&] {
        AdcFrame f;
        const clk::time_point t0 = clk::now();
        got = r.next_adc_frame(f, milliseconds(10000), &why);
        returned_at = clk::now();
        waited = ms_since(t0);
    });
    std::this_thread::sleep_for(milliseconds(100));
    const clk::time_point t_stop = clk::now();
    CHECK(static_cast<bool>(r.stop()));
    const long long stop_ms = ms_since(t_stop);
    consumer.join();
    const long long woke_ms = std::chrono::duration_cast<milliseconds>(returned_at - t_stop).count();
    std::cout << "    consumer returned " << woke_ms << " ms after stop() began (stop() took " << stop_ms
              << " ms)" << std::endl;
    CHECK(!got);
    CHECK(why.code == Code::stopped);
    CHECK(waited >= 90 && waited < 3000);
    CHECK(woke_ms < 200);  // woken at the start of stop(), not after it
}

// A packet source whose pop() throws after a few packets (e.g. bad_alloc in
// the driver's worker thread)
class ThrowingSource : public ReplayPacketSource {
public:
    bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) override {
        if (pops_.fetch_add(1) >= 3) throw std::runtime_error("boom from the packet source");
        return ReplayPacketSource::pop(buf, len, timeout);
    }

private:
    std::atomic<int> pops_{0};
};

// core-13 review S8: an exception in the DCA worker thread ends the stream,
// not the process; next_adc_frame reports it and stop() still works
TEST_CASE(worker_exception_is_reported_not_fatal) {
    const RadarConfig cfg = load("worker_throws");
    auto cli = std::make_shared<FakeCli>();
    auto src = std::make_shared<ThrowingSource>();
    auto opened = Radar::open(cfg, {cli, src});
    CHECK(static_cast<bool>(opened));
    if (!opened) return;
    Radar& r = **opened;
    WarnCapture errors;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    uint32_t seq = 1;
    for (const auto& p : dca_test::frame_packets(0, static_cast<size_t>(cfg.frame_shape().bytes), 1, seq)) src->push(p);
    AdcFrame f;
    Status why;
    const clk::time_point t0 = clk::now();
    CHECK(!r.next_adc_frame(f, milliseconds(5000), &why));
    CHECK(why.code == Code::io_error);
    CHECK(why.message.find("boom from the packet source") != std::string::npos);
    CHECK(ms_since(t0) < 3000);  // woken by the failure, not the timeout
    bool logged = false;
    for (const std::string& e : errors.get()) logged = logged || e.find("worker stopped: boom") != std::string::npos;
    CHECK(logged);
    CHECK(!r.next_adc_frame(f, milliseconds(10), &why));
    CHECK(why.code == Code::io_error);
    CHECK(static_cast<bool>(r.stop()));
    CHECK_EQ(cli->count("sensorStop\n"), size_t(2));
}

TEST_CASE(config_once_per_boot) {
    auto once = [](json& j) {
        j["cli"]["port"] = "/dev/fake-cascade-cli";
        j["board_overrides"] = {{"lifecycle", {{"config_once_per_boot", true}}}};
    };
    RadarConfig cfg = load("once", once);
    Rig rig(cfg);
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    const size_t sent = rig.cli->writes();
    const Status again = r.configure();
    CHECK(again.code == Code::already_configured);
    CHECK_EQ(rig.cli->writes(), sent);  // nothing sent
    CHECK(static_cast<bool>(r.start()));  // the board still holds the cfg
    r.stop();
    // a new Radar on the same port in this process: still nothing sent
    Rig rig2(cfg);
    if (!rig2.radar) return;
    CHECK(rig2.radar->configure().code == Code::already_configured);
    CHECK_EQ(rig2.cli->writes(), size_t(0));
}

TEST_CASE(stall_policy) {
    Rig rig(load("stall", [](json& j) { j["runtime"] = {{"stall_timeout_ms", 200}}; }));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    WarnCapture warns;
    AdcFrame f;
    Status why;
    clk::time_point t0 = clk::now();
    CHECK(!r.next_adc_frame(f, milliseconds(2000), &why));  // no packets at all
    CHECK(why.code == Code::stalled);
    CHECK(ms_since(t0) >= 190 && ms_since(t0) < 1000);
    CHECK_EQ(r.stats().stalls, uint64_t(1));
    CHECK(!r.next_adc_frame(f, milliseconds(100), &why));  // same stall: reported once
    CHECK(why.code == Code::timeout);
    CHECK_EQ(r.stats().stalls, uint64_t(1));
    // a frame again (complete on its own), then a second stall
    rig.send_frame(0, 1);
    CHECK(r.next_adc_frame(f, milliseconds(2000), &why));
    t0 = clk::now();
    CHECK(!r.next_adc_frame(f, milliseconds(2000), &why));
    CHECK(why.code == Code::stalled);
    CHECK_EQ(r.stats().stalls, uint64_t(2));
    size_t stall_warnings = 0;
    for (const std::string& w : warns.get()) {
        if (w.find("no ADC frame for 200 ms") != std::string::npos) stall_warnings++;
    }
    CHECK_EQ(stall_warnings, size_t(2));
    r.stop();
}

TEST_CASE(stall_policy_off_by_default) {
    Rig rig(load("nostall"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    AdcFrame f;
    Status why;
    CHECK(!r.next_adc_frame(f, milliseconds(300), &why));
    CHECK(why.code == Code::timeout);
    CHECK_EQ(r.stats().stalls, uint64_t(0));
    r.stop();
}

TEST_CASE(write_error_during_stop_does_not_throw_and_closes_files) {
    Rig rig(load("unplug"));
    if (!rig.radar) return;
    Radar& r = *rig.radar;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));
    for (int k = 0; k < 3; k++) rig.send_frame(static_cast<uint64_t>(k), static_cast<uint16_t>(k + 1));
    const clk::time_point t0 = clk::now();
    while (r.stats().frames < 3 && ms_since(t0) < 3000) std::this_thread::sleep_for(milliseconds(5));
    rig.cli->fail_from_now(FakeCli::Fail::throw_system_error);  // the radar's USB goes away
    bool threw = false;
    Status s;
    try {
        s = r.stop();
    } catch (...) {
        threw = true;
    }
    CHECK(!threw);
    CHECK(s.code == Code::io_error);
    CHECK(s.message.find("sensorStop") != std::string::npos);
    const uint64_t frames = r.stats().frames;
    CHECK_EQ(frames, uint64_t(3));
    struct stat sb;
    CHECK(stat((kRoot + "/unplug/adc_data.bin").c_str(), &sb) == 0);
    CHECK_EQ(static_cast<uint64_t>(sb.st_size), frames * rig.bytes_per_frame);
    // destructor after a failed stop: no second stop, no throw
    try {
        rig.radar.reset();
    } catch (...) {
        threw = true;
    }
    CHECK(!threw);
    CHECK_EQ(rig.cli->count("sensorStop\n"), size_t(2));
}

TEST_CASE(output_dir_created_on_open) {
    const std::string dir = kRoot + "/made/on/open";
    RadarConfig cfg = load("mkdir", [&](json& j) { j["output"]["dir"] = dir; });
    CHECK(!std::filesystem::exists(dir));
    Rig rig(cfg);
    CHECK(std::filesystem::is_directory(dir));
    CHECK(std::filesystem::exists(dir + "/adc_data.bin"));

    const std::string file = kRoot + "/plain_file";
    std::ofstream(file) << "x";
    RadarConfig bad = load("mkdir_bad", [&](json& j) { j["output"]["dir"] = file + "/captures"; });
    auto r = Radar::open(bad, {std::make_shared<FakeCli>(), std::make_shared<ReplayPacketSource>()});
    CHECK(!r);
    CHECK(r.status.code == Code::output_dir);
    CHECK(r.status.message.find(file + "/captures") != std::string::npos);
}

TEST_CASE(moved_radar_keeps_working_and_the_source_is_empty) {
    Rig rig(load("move"));
    if (!rig.radar) return;
    Radar moved(std::move(*rig.radar));
    CHECK(static_cast<bool>(moved.configure()));
    CHECK(rig.radar->configure().code == Code::invalid_state);  // moved-from
    CHECK(static_cast<bool>(moved.start()));
    CHECK(static_cast<bool>(moved.stop()));
}

// core-15 P11: runtime.worker_cpu pins the DCA worker thread. The packet
// source's pop() runs on that thread, so it records the thread's affinity.
class AffinityRecordingSource : public ReplayPacketSource {
public:
    bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) override {
        cpu_set_t set;
        CPU_ZERO(&set);
        if (sched_getaffinity(0, sizeof(set), &set) == 0) {
            std::lock_guard<std::mutex> l(m_);
            cpus_ = CPU_COUNT(&set);
            on_cpu0_ = CPU_ISSET(0, &set);
        }
        return ReplayPacketSource::pop(buf, len, timeout);
    }
    int cpus() const { std::lock_guard<std::mutex> l(m_); return cpus_; }
    bool on_cpu0() const { std::lock_guard<std::mutex> l(m_); return on_cpu0_; }

private:
    mutable std::mutex m_;
    int cpus_ = -1;
    bool on_cpu0_ = false;
};

TEST_CASE(worker_cpu_pins_the_dca_worker_thread) {
    for (const bool pin : {true, false}) {
        const RadarConfig cfg = load(pin ? "worker_cpu0" : "worker_cpu_null", [pin](json& j) {
            j["runtime"] = {{"worker_cpu", pin ? json(0) : json(nullptr)}, {"worker_priority", 10}};
        });
        auto cli = std::make_shared<FakeCli>();
        auto src = std::make_shared<AffinityRecordingSource>();
        auto opened = Radar::open(cfg, {cli, src});
        CHECK(static_cast<bool>(opened));
        if (!opened) return;
        Radar& r = **opened;
        CHECK(static_cast<bool>(r.configure()));
        CHECK(static_cast<bool>(r.start()));  // SCHED_RR 10 without cap_sys_nice: a warning, not an error
        const clk::time_point t0 = clk::now();
        while (src->cpus() < 0 && ms_since(t0) < 3000) std::this_thread::sleep_for(milliseconds(5));
        CHECK(static_cast<bool>(r.stop()));
        if (pin) {
            CHECK_EQ(src->cpus(), 1);
            CHECK(src->on_cpu0());
        } else {
            // null keeps today's behaviour: the worker may run on every CPU the process may
            cpu_set_t mine;
            CPU_ZERO(&mine);
            sched_getaffinity(0, sizeof(mine), &mine);
            CHECK_EQ(src->cpus(), CPU_COUNT(&mine));
        }
    }
}

TEST_MAIN()
