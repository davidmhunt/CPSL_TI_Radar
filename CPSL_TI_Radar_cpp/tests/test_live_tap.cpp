// Live tap (gui-36 Step 1): the wire encoder against golden bytes, and the
// mailbox/writer over a real pipe pair: a slow reader costs skipped frames but
// push never blocks, a closed reader disables the tap without killing the
// process (SIGPIPE), --tap-adc-every K sends frames 0, K, 2K ...
//
// The golden message stream is tests/data/live_tap_golden.bin; tests/test_radar_gui_tap_wire.py
// parses the same file with radar_gui/tap.py. Regenerate (only for a deliberate wire change):
//   LIVE_TAP_WRITE_GOLDEN=1 ./test_live_tap
#include "test_harness.hpp"
#include "fake_transports.hpp"

#include "LiveTap.hpp"

#include <fcntl.h>
#include <poll.h>
#include <unistd.h>

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <thread>

using namespace cpsl::radar;
using clk = std::chrono::steady_clock;
using std::chrono::milliseconds;

namespace {

struct Pipe {
    int rd = -1, wr = -1;
    Pipe() {
        int fds[2];
        CHECK(::pipe(fds) == 0);
        rd = fds[0];
        wr = fds[1];
    }
    ~Pipe() {
        if (rd >= 0) ::close(rd);
        if (wr >= 0) ::close(wr);
    }
    void close_read() {
        ::close(rd);
        rd = -1;
    }
    void give_write_end() { wr = -1; }  // handed to a LiveTap, which closes it
};

struct Msg {
    uint8_t type = 0;
    std::string body;
};

bool read_exact(int fd, void* buf, size_t n, int timeout_ms) {
    uint8_t* p = static_cast<uint8_t*>(buf);
    size_t got = 0;
    while (got < n) {
        pollfd pf{fd, POLLIN, 0};
        if (::poll(&pf, 1, timeout_ms) <= 0) return false;
        const ssize_t r = ::read(fd, p + got, n - got);
        if (r <= 0) return false;
        got += static_cast<size_t>(r);
    }
    return true;
}

bool read_msg(int fd, Msg& m, int timeout_ms = 2000) {
    uint8_t h[4];
    if (!read_exact(fd, h, 4, timeout_ms)) return false;
    const uint32_t len = h[0] | (h[1] << 8) | (h[2] << 16) | (static_cast<uint32_t>(h[3]) << 24);
    std::string body(len, '\0');
    if (len == 0 || !read_exact(fd, &body[0], len, timeout_ms)) return false;
    m.type = static_cast<uint8_t>(body[0]);
    m.body = body.substr(1);
    return true;
}

std::string prefix(size_t json_len, char type) {  // u32 LE length (< 256 here) + type
    std::string p(4, '\0');
    p[0] = static_cast<char>(json_len + 1);
    return p + type;
}

double since_ms(clk::time_point t0) { return std::chrono::duration<double, std::milli>(clk::now() - t0).count(); }

std::string as_string(const std::vector<uint8_t>& v) { return std::string(v.begin(), v.end()); }

PointCloud sample_cloud() {
    PointCloud c;
    c.frame_number = 7;
    Point a;
    a.x = 1.5f; a.y = 2.25f; a.z = 0.0f; a.v = -0.5f; a.snr_db = 20.0f; a.noise_db = 5.0f;
    Point b;
    b.x = std::nanf(""); b.y = 1.0f; b.z = -1.25f; b.v = 0.1f; b.snr_db = std::nanf(""); b.noise_db = 0.0f;
    c.points = {a, b};
    return c;
}

AdcFrame sample_adc(uint64_t index, int rx = 2, int samples = 3, int chirps = 2) {
    AdcFrame f;
    f.index = index;
    f.missing_bytes = 16;
    f.data.assign(rx, std::vector<std::vector<std::complex<int16_t>>>(
                          samples, std::vector<std::complex<int16_t>>(chirps)));
    for (int r = 0; r < rx; r++)
        for (int s = 0; s < samples; s++)
            for (int c = 0; c < chirps; c++) {
                const int v = r * 100 + s * 10 + c;
                f.data[r][s][c] = std::complex<int16_t>(static_cast<int16_t>(v), static_cast<int16_t>(-v - 1));
            }
    return f;
}

std::vector<uint8_t> golden_stream() {
    std::vector<uint8_t> all = livetap::encode_hello("IWR1843", true, true, 3);
    for (const auto& m : {livetap::encode_points(sample_cloud(), 1700000000.25), livetap::encode_adc(sample_adc(6))})
        all.insert(all.end(), m.begin(), m.end());
    return all;
}

}  // namespace

TEST_CASE(hello_golden_bytes) {
    const std::vector<uint8_t> m = livetap::encode_hello("IWR1843", true, true, 3);
    const std::string json = "{\"version\":1,\"board\":\"IWR1843\",\"streams\":[\"points\",\"adc\"],\"adc_every\":3}";
    CHECK_EQ(as_string(m), prefix(json.size(), 1) + json);
    const std::string only_adc = as_string(livetap::encode_hello("X\"1", false, true, 0)).substr(5);
    CHECK_EQ(only_adc, std::string("{\"version\":1,\"board\":\"X\\\"1\",\"streams\":[\"adc\"],\"adc_every\":0}"));
}

TEST_CASE(points_golden_bytes_nan_becomes_null) {
    const std::vector<uint8_t> m = livetap::encode_points(sample_cloud(), 1700000000.25);
    const std::string json =
        "{\"type\":\"frame\",\"frame\":7,\"n\":2,\"t\":1700000000.250000,"
        "\"pts\":[[1.5,2.25,0,-0.5,20,5],[null,1,-1.25,0.1,null,0]]}";
    CHECK_EQ(as_string(m), prefix(json.size(), 2) + json);
    PointCloud empty;
    const std::string e = as_string(livetap::encode_points(empty, 1.0)).substr(5);
    CHECK_EQ(e, std::string("{\"type\":\"frame\",\"frame\":0,\"n\":0,\"t\":1.000000,\"pts\":[]}"));
}

TEST_CASE(adc_golden_bytes_layout_is_rx_sample_chirp_iq_pairs) {
    const std::vector<uint8_t> m = livetap::encode_adc(sample_adc(6));
    const std::string head =
        "{\"index\":6,\"shape\":[2,3,2],\"missing_bytes\":16,\"layout\":\"rx,sample,chirp\",\"iq_order\":\"IQ\"}\n";
    const size_t payload = 2 * 3 * 2 * 4;
    const uint32_t len = static_cast<uint32_t>(1 + head.size() + payload);
    CHECK_EQ(m.size(), static_cast<size_t>(4 + len));
    CHECK_EQ(m[0], static_cast<uint8_t>(len & 0xff));
    CHECK_EQ(m[1], static_cast<uint8_t>(len >> 8));
    CHECK_EQ(m[4], static_cast<uint8_t>(3));
    CHECK_EQ(std::string(m.begin() + 5, m.begin() + 5 + head.size()), head);
    const uint8_t* d = m.data() + 5 + head.size();
    auto i16 = [&](size_t k) { return static_cast<int16_t>(d[2 * k] | (d[2 * k + 1] << 8)); };
    // [rx 1][sample 2][chirp 1] = value 121: sample index ((1*3)+2)*2+1 = 11, I then Q
    CHECK_EQ(i16(11 * 2), static_cast<int16_t>(121));
    CHECK_EQ(i16(11 * 2 + 1), static_cast<int16_t>(-122));
    CHECK_EQ(i16(1 * 2), static_cast<int16_t>(1));      // [0][0][1]
    CHECK_EQ(i16(2 * 2), static_cast<int16_t>(10));     // [0][1][0]
}

TEST_CASE(golden_file_matches_the_encoder) {
    const std::string path = std::string(TEST_DATA_DIR) + "/live_tap_golden.bin";
    const std::vector<uint8_t> now = golden_stream();
    if (std::getenv("LIVE_TAP_WRITE_GOLDEN")) {
        std::ofstream(path, std::ios::binary).write(reinterpret_cast<const char*>(now.data()), now.size());
    }
    std::ifstream in(path, std::ios::binary);
    CHECK(static_cast<bool>(in));
    std::vector<uint8_t> file((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    CHECK(file == now);
}

TEST_CASE(hello_comes_first_then_points_over_the_pipe) {
    Pipe p;
    LiveTap tap(p.wr, 0);
    p.give_write_end();
    tap.start("IWR1843", true, false);
    tap.push_points(sample_cloud());
    Msg m;
    CHECK(read_msg(p.rd, m));
    CHECK_EQ(m.type, static_cast<uint8_t>(1));
    CHECK(m.body.find("\"streams\":[\"points\"]") != std::string::npos);
    CHECK(read_msg(p.rd, m));
    CHECK_EQ(m.type, static_cast<uint8_t>(2));
    CHECK(m.body.find("\"frame\":7") != std::string::npos);
    CHECK_EQ(tap.sent(), 1u);
    CHECK_EQ(tap.stats_line(2.5), std::string("stats v1 tap t=2.500 sent=1 skipped=0 adc_sent=0\n"));
}

TEST_CASE(slow_reader_skips_frames_and_push_never_blocks) {
    Pipe p;
    LiveTap tap(p.wr, 0);
    p.give_write_end();
    tap.start("IWR1843", true, false);
    PointCloud c;
    c.points.assign(300, Point());  // ~12 KB per message: the 64 KB pipe is full after a few
    const int pushes = 300;
    int over_1ms = 0;
    double worst_ms = 0;
    for (int i = 0; i < pushes; i++) {
        c.frame_number = static_cast<uint32_t>(i);
        const clk::time_point t0 = clk::now();
        tap.push_points(c);
        const double ms = since_ms(t0);
        worst_ms = std::max(worst_ms, ms);
        if (ms >= 1.0) over_1ms++;
        std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
    CHECK(over_1ms <= 3);        // a descheduled thread, not a blocked write
    CHECK(worst_ms < 50.0);
    CHECK(tap.skipped() > 0);
    CHECK(tap.enabled());
    // drain: the newest frame must arrive (latest wins) and the counters must add up
    Msg m;
    uint32_t last = 0;
    uint64_t got = 0;
    while (tap.sent() + tap.skipped() < static_cast<uint64_t>(pushes) || got < tap.sent()) {
        if (!read_msg(p.rd, m, 500)) break;
        if (m.type != 2) continue;
        got++;
        const size_t at = m.body.find("\"frame\":") + 8;
        last = static_cast<uint32_t>(std::atoi(m.body.c_str() + at));
    }
    CHECK_EQ(last, static_cast<uint32_t>(pushes - 1));
    CHECK_EQ(tap.sent() + tap.skipped(), static_cast<uint64_t>(pushes));
    CHECK_EQ(got, tap.sent());
}

TEST_CASE(closed_reader_disables_the_tap_without_killing_the_process) {
    WarnCapture warns;
    Pipe p;
    LiveTap tap(p.wr, 0);
    p.give_write_end();
    tap.start("IWR1843", true, false);
    p.close_read();
    for (int i = 0; i < 100 && tap.enabled(); i++) {
        tap.push_points(sample_cloud());
        std::this_thread::sleep_for(milliseconds(10));
    }
    CHECK(!tap.enabled());  // EPIPE, and we are still alive (SIGPIPE ignored)
    const clk::time_point t0 = clk::now();
    for (int i = 0; i < 50; i++) tap.push_points(sample_cloud());  // no-ops
    CHECK(since_ms(t0) < 50.0);
    int tap_warnings = 0;
    for (const std::string& w : warns.get()) tap_warnings += w.find("live tap disabled") != std::string::npos;
    CHECK_EQ(tap_warnings, 1);  // one warning, not one per frame
    tap.stop();
}

TEST_CASE(stop_does_not_hang_on_a_full_pipe) {
    Pipe p;
    LiveTap tap(p.wr, 0);
    p.give_write_end();
    tap.start("IWR1843", true, false);
    PointCloud c;
    c.points.assign(2000, Point());
    for (int i = 0; i < 20; i++) tap.push_points(c);
    std::this_thread::sleep_for(milliseconds(100));
    const clk::time_point t0 = clk::now();
    tap.stop();
    CHECK(since_ms(t0) < 1000.0);
}

TEST_CASE(adc_every_3_sends_frames_0_3_6) {
    Pipe p;
    LiveTap tap(p.wr, 3);
    p.give_write_end();
    tap.start("IWR1843", false, true);
    for (int i = 0; i < 7; i++) {
        tap.offer_adc(sample_adc(static_cast<uint64_t>(i), 1, 1, 2));
        if (i % 3 == 0) {
            for (int w = 0; w < 200 && tap.adc_sent() < static_cast<uint64_t>(i / 3 + 1); w++)
                std::this_thread::sleep_for(milliseconds(5));
        }
    }
    CHECK_EQ(tap.adc_sent(), 3u);
    CHECK_EQ(tap.skipped(), 0u);
    Msg m;
    CHECK(read_msg(p.rd, m));
    CHECK_EQ(m.type, static_cast<uint8_t>(1));
    CHECK(m.body.find("\"adc_every\":3") != std::string::npos);
    for (int expect : {0, 3, 6}) {
        CHECK(read_msg(p.rd, m));
        CHECK_EQ(m.type, static_cast<uint8_t>(3));
        const std::string want = "{\"index\":" + std::to_string(expect) + ",";
        CHECK(m.body.find(want) == 0);
    }
    PointCloud none;
    LiveTap off(-1, 0);  // adc_every 0: offer_adc is a no-op (never started: nothing to join)
    off.offer_adc(sample_adc(0));
    CHECK_EQ(off.adc_sent(), 0u);
}

TEST_MAIN()
