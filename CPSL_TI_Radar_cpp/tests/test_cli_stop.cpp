// No-throw stop path (directive core-11 Step 6; RESULTS.md Finding 2).
//
// Unplugging the radar's USB mid-capture made the sensorStop write throw an
// uncaught boost::system::system_error ("write: Input/output error") and the
// driver died with SIGABRT before closing its files. CLIController now talks
// to a cpsl::radar::ByteStream and turns every write/read failure (thrown or
// returned) into a false return plus io_error(); Radar::stop() runs every
// step anyway and reports the failure.
//
// Part 1 drives CLIController over a fake stream. Part 2 runs a whole Radar
// on a fake CLI stream and a loopback fake DCA1000 (127.0.0.2, UDP): no
// serial port and no real board is opened.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "ByteStream.hpp"
#include "fake_transports.hpp"
#include "CLIController.hpp"
#include "Log.hpp"
#include "Radar.hpp"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#include <atomic>
#include <boost/system/system_error.hpp>
#include <deque>
#include <map>
#include <pty.h>
#include <mutex>
#include <thread>

static SystemConfigReader serial_free_config(const std::string& name) {
    return SystemConfigReader(dca_test::write_system_config(name, dca_test::tmp_dir(), false));
}

static void check_stop_fails_without_throwing(FakeCli::Fail mode) {
    SystemConfigReader sys = serial_free_config("cli_unit");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    CHECK(cli.sendStartCommand());
    CHECK(!cli.io_error());
    fake->fail_from_now(mode);
    bool threw = false, ok = true;
    try {
        ok = cli.sendStopCommand();
    } catch (...) {
        threw = true;
    }
    CHECK(!threw);
    CHECK(!ok);
    CHECK(cli.io_error());
    CHECK_EQ(fake->attempted.back(), std::string("sensorStop\n"));
}

TEST_CASE(stop_write_that_throws_returns_false) {
    check_stop_fails_without_throwing(FakeCli::Fail::throw_system_error);
}

TEST_CASE(stop_write_that_returns_eio_returns_false) {
    check_stop_fails_without_throwing(FakeCli::Fail::return_eio);
}

TEST_CASE(stop_read_error_returns_false) {
    check_stop_fails_without_throwing(FakeCli::Fail::read_eio);
}

TEST_CASE(missing_ack_is_not_an_io_error) {
    SystemConfigReader sys = serial_free_config("cli_noack");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    fake->fail_from_now(FakeCli::Fail::no_reply);
    CHECK(!cli.sendStopCommand());
    CHECK(!cli.io_error());
}

TEST_CASE(uninitialized_controller_does_not_throw) {
    CLIController cli;
    CHECK(!cli.sendStopCommand());
    CHECK(!cli.send_config_to_IWR());
}

// ---- Step 3 of core-13: sensorStop ack window, per-command io_error, timed write ----

// The IWR1843 fixture: cmd_timeout_ms 100, frame period 100 ms. sensorStop is
// acknowledged only after the current frame ends, so a 100 ms window missed
// it on every healthy bench stop (core-06 review S1).
TEST_CASE(sensorStop_ack_after_1_5x_cmd_timeout_is_no_warning) {
    SystemConfigReader sys = serial_free_config("cli_slow_stop");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    cli.set_frame_period_ms(100.0f);
    CHECK_EQ(cli.stop_timeout_ms(), 300);  // max(100, 100 + 200)
    fake->reply_delay["sensorStop"] = std::chrono::milliseconds(150);  // 1.5 x cmd_timeout_ms
    WarnCapture warns;
    CHECK(cli.sendStopCommand());
    CHECK(!cli.io_error());
    CHECK(warns.get().empty());
    CHECK_EQ(fake->write_timeouts.back().count(), 300);  // the write is bounded by the same window
}

TEST_CASE(stop_timeout_override_and_floor) {
    // board_overrides.cli.stop_timeout_ms wins over the computed value
    json j;
    {
        std::ifstream f(dca_test::write_system_config("cli_stop_override", dca_test::tmp_dir(), false));
        j = json::parse(f);
    }
    j["board_overrides"] = {{"cli", {{"stop_timeout_ms", 750}}}};
    const std::string path = dca_test::tmp_dir() + "/cli_stop_override.json";
    std::ofstream(path) << j.dump();
    SystemConfigReader sys(path);
    CHECK(sys.initialized);
    CLIController cli;
    CHECK(cli.initialize(sys, std::make_shared<FakeCli>()));
    cli.set_frame_period_ms(100.0f);
    CHECK_EQ(cli.stop_timeout_ms(), 750);
    // computed: never below cmd_timeout_ms
    CLIController cli2;
    CHECK(cli2.initialize(serial_free_config("cli_stop_floor"), std::make_shared<FakeCli>()));
    CHECK_EQ(cli2.stop_timeout_ms(), 200);  // no frame period known: max(100, 0 + 200)
}

// core-11 review S2: io_error_ was sticky, so a prompt-read hiccup after a
// "Done" made a later plain timeout look like an I/O error.
TEST_CASE(prompt_read_error_then_timeout_is_reported_as_a_timeout) {
    SystemConfigReader sys = serial_free_config("cli_sticky");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    fake->prompt_error_on = "sensorStart";
    CHECK(cli.sendStartCommand());  // "Done" arrived: the command succeeded
    CHECK(cli.io_error());          // the prompt read after it failed
    fake->fail_from_now(FakeCli::Fail::no_reply);
    WarnCapture warns;
    CHECK(!cli.sendStopCommand());
    CHECK(!cli.io_error());  // a plain timeout, not an I/O error
    const std::vector<std::string> w = warns.get();
    CHECK_EQ(w.size(), size_t(1));
    CHECK(!w.empty() && w[0].find("no 'Done' for 'sensorStop'") != std::string::npos);
}

// core-11 review S5: a blocking write could hang stop() on a wedged device.
TEST_CASE(write_that_never_completes_returns_within_the_timeout) {
    SystemConfigReader sys = serial_free_config("cli_hang");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    cli.set_frame_period_ms(100.0f);
    fake->fail_from_now(FakeCli::Fail::write_hangs);
    const auto t0 = std::chrono::steady_clock::now();
    const bool ok = cli.sendStopCommand();
    const long long ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
    CHECK(!ok);
    CHECK(cli.io_error());
    CHECK(ms >= 290);   // waited the stop window (300 ms) ...
    CHECK(ms < 300 + 500);  // ... and no longer
}

// The real SerialPortStream: a pty whose master never reads fills up and
// blocks the writer; the timed write must give up.
TEST_CASE(serial_port_write_times_out_on_a_full_pty) {
    int master = -1, slave = -1;
    char name[256] = {0};
    CHECK(openpty(&master, &slave, name, nullptr, nullptr) == 0);
    if (master < 0) return;
    close(slave);  // SerialPortStream opens it by name
    std::string err;
    std::shared_ptr<cpsl::radar::SerialPortStream> port = cpsl::radar::SerialPortStream::open(name, 115200, err);
    CHECK(port != nullptr);
    if (port) {
        const std::vector<uint8_t> big(8 * 1024 * 1024, 'x');
        const auto t0 = std::chrono::steady_clock::now();
        const std::error_code ec = port->write(big.data(), big.size(), std::chrono::milliseconds(300));
        const long long ms =
            std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
        CHECK(ec == std::errc::timed_out);
        CHECK(ms >= 290);
        CHECK(ms < 300 + 1000);
    }
    port.reset();
    close(master);
}

// ---- Part 2: Radar over a fake CLI and a loopback fake DCA1000 (real UdpPacketSource) ----

class FakeDca {
public:
    FakeDca(const std::string& ip, int cmd_port) {
        fd_ = socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_port = htons(static_cast<uint16_t>(cmd_port));
        a.sin_addr.s_addr = inet_addr(ip.c_str());
        bound = bind(fd_, reinterpret_cast<sockaddr*>(&a), sizeof a) == 0;
        timeval tv{0, 100000};
        setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        if (bound) thread_ = std::thread([this] { serve(); });
    }
    ~FakeDca() {
        stop_ = true;
        if (thread_.joinable()) thread_.join();
        close(fd_);
    }
    bool saw(uint16_t code) {
        std::lock_guard<std::mutex> l(m_);
        for (uint16_t c : codes) if (c == code) return true;
        return false;
    }
    bool bound = false;

private:
    void serve() {
        while (!stop_) {
            uint8_t b[64];
            sockaddr_in from{};
            socklen_t fl = sizeof from;
            ssize_t n = recvfrom(fd_, b, sizeof b, 0, reinterpret_cast<sockaddr*>(&from), &fl);
            if (n < 4) continue;
            const uint16_t code = static_cast<uint16_t>(b[2] | (b[3] << 8));
            {
                std::lock_guard<std::mutex> l(m_);
                codes.push_back(code);
            }
            const uint16_t status = code == 0xE ? 2 : 0;  // READ_FPGA_VERSION: v2.0
            uint8_t r[8] = {0x5A, 0xA5, b[2], b[3], static_cast<uint8_t>(status & 0xFF),
                            static_cast<uint8_t>(status >> 8), 0xAA, 0xEE};
            sendto(fd_, r, sizeof r, 0, reinterpret_cast<sockaddr*>(&from), fl);
        }
    }
    int fd_ = -1;
    std::atomic<bool> stop_{false};
    std::thread thread_;
    std::mutex m_;
    std::vector<uint16_t> codes;
};

TEST_CASE(radar_stop_survives_an_unplugged_cli_and_still_closes_the_bin) {
    const int base = 42000 + static_cast<int>(getpid() % 2000) * 2;
    const int cmd_port = base, data_port = base + 1;
    FakeDca dca("127.0.0.2", cmd_port);
    CHECK(dca.bound);
    if (!dca.bound) return;

    const std::string out = dca_test::tmp_dir() + "/cli_stop_out";
    const std::string cfg_path =
        dca_test::write_system_config("cli_stop", out, true, "127.0.0.2", cmd_port, data_port);
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();

    bool threw = false;
    try {
        auto cfg = cpsl::radar::RadarConfig::load(cfg_path);
        CHECK(static_cast<bool>(cfg));
        if (!cfg) return;
        cpsl::radar::Transports t;
        t.cli = fake;  // packets: null = the real UdpPacketSource
        auto opened = cpsl::radar::Radar::open(*cfg, t);
        CHECK(static_cast<bool>(opened));
        if (!opened) return;
        cpsl::radar::Radar& radar = **opened;
        CHECK(static_cast<bool>(radar.configure()));
        CHECK(fake->writes() > 5);  // the cfg went through the fake CLI
        CHECK(dca.saw(0x3));        // CONFIG_FPGA_GEN
        CHECK(static_cast<bool>(radar.start()));
        CHECK(dca.saw(0x5));        // RECORD_START

        // stream K frames from the "DCA1000" to the driver's data port
        const size_t B = static_cast<size_t>(cfg->frame_shape().bytes);
        int tx = socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in to{};
        to.sin_family = AF_INET;
        to.sin_port = htons(static_cast<uint16_t>(data_port));
        to.sin_addr.s_addr = inet_addr("127.0.0.1");
        const int K = 3;
        uint32_t seq = 1;
        for (int k = 0; k < K; k++) {
            for (const auto& p : dca_test::frame_packets(static_cast<uint64_t>(k), B, static_cast<uint16_t>(k + 1), seq)) {
                sendto(tx, p.data(), p.size(), 0, reinterpret_cast<sockaddr*>(&to), sizeof to);
                std::this_thread::sleep_for(std::chrono::microseconds(50));
            }
            cpsl::radar::AdcFrame f;
            CHECK(radar.next_adc_frame(f, std::chrono::milliseconds(3000)));
            CHECK_EQ(f.index, static_cast<uint64_t>(k));
            CHECK_EQ(f.data.empty() ? -1 : f.data[0][0][0].real(), k + 1);
        }
        close(tx);
        CHECK(radar.stats().rcvbuf_bytes > 0);

        // the radar's USB goes away: sensorStop's write throws
        fake->fail_from_now(FakeCli::Fail::throw_system_error);
        const cpsl::radar::Status st = radar.stop();
        CHECK(st.code == cpsl::radar::Code::io_error);
        CHECK_EQ(fake->attempted.back(), std::string("sensorStop\n"));
        CHECK(dca.saw(0x6));          // RECORD_STOP still sent
        struct stat sb;
        CHECK(stat((out + "/adc_data.bin").c_str(), &sb) == 0);
        CHECK_EQ(static_cast<long long>(sb.st_size), static_cast<long long>(K) * static_cast<long long>(B));

        // idempotent: no second sensorStop
        const size_t n = fake->writes();
        CHECK(radar.stop() == st);
        CHECK_EQ(fake->writes(), n);
    } catch (...) {
        threw = true;  // includes the Radar destructor
    }
    CHECK(!threw);
}

TEST_MAIN()
