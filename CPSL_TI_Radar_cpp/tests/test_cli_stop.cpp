// No-throw stop path (directive core-11 Step 6; RESULTS.md Finding 2).
//
// Unplugging the radar's USB mid-capture made the sensorStop write throw an
// uncaught boost::system::system_error ("write: Input/output error") and the
// driver died with SIGABRT before closing its files. CLIController now talks
// to a cpsl::radar::ByteStream and turns every write/read failure (thrown or
// returned) into a false return plus io_error(); Runner::stop() runs every
// step anyway and reports the failure.
//
// Part 1 drives CLIController over a fake stream. Part 2 runs a whole Runner
// on a fake CLI stream and a loopback fake DCA1000 (127.0.0.2, UDP): no
// serial port and no real board is opened.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "ByteStream.hpp"
#include "CLIController.hpp"
#include "Log.hpp"
#include "Runner.hpp"

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

// A scripted CLI: every written line is answered with "Done" + the prompt.
// After `fail_after` writes, writes fail: by throwing (as boost::asio::write
// does on an unplugged port), by returning EIO, or by hanging until the
// write's timeout (a wedged CDC device). reply_delay holds a command's reply
// back; prompt_error_on drops one command's prompt and fails the next read.
class FakeCli : public cpsl::radar::ByteStream {
public:
    enum class Fail { none, throw_system_error, return_eio, read_eio, no_reply, write_hangs };
    using clock = std::chrono::steady_clock;

    std::error_code write(const uint8_t* data, size_t len, std::chrono::milliseconds timeout) override {
        std::unique_lock<std::mutex> l(m_);
        const std::string line(reinterpret_cast<const char*>(data), len);
        const std::string cmd = line.substr(0, line.size() - 1);
        attempted.push_back(line);
        write_timeouts.push_back(timeout);
        if (fail != Fail::none && writes_ok >= fail_after) {
            if (fail == Fail::throw_system_error)
                throw boost::system::system_error(boost::system::error_code(EIO, boost::system::system_category()),
                                                  "write");
            if (fail == Fail::return_eio) return std::error_code(EIO, std::system_category());
            if (fail == Fail::write_hangs) {
                l.unlock();
                std::this_thread::sleep_for(timeout);  // never completes: the timeout ends it
                return std::make_error_code(std::errc::timed_out);
            }
            if (fail == Fail::no_reply) { writes_ok++; return {}; }
            // read_eio: the write lands, the read fails
            writes_ok++;
            read_error_ = true;
            return {};
        }
        writes_ok++;
        auto d = reply_delay.find(cmd);
        const clock::time_point at = clock::now() + (d == reply_delay.end() ? std::chrono::milliseconds(0) : d->second);
        if (cmd == prompt_error_on) {
            pending_.push_back({at, "\r\n" + cmd + "\r\nDone\r\n"});
            prompt_error_ = true;
        } else {
            pending_.push_back({at, "\r\n" + cmd + "\r\nDone\r\nmmwDemo:/>"});
        }
        return {};
    }

    std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) override {
        n = 0;
        std::unique_lock<std::mutex> l(m_);
        if (read_error_) return std::error_code(EIO, std::system_category());
        if (pending_.empty()) {
            if (prompt_error_) {
                prompt_error_ = false;
                return std::error_code(EIO, std::system_category());
            }
            l.unlock();
            std::this_thread::sleep_for(std::min(timeout, std::chrono::milliseconds(5)));
            return std::make_error_code(std::errc::timed_out);
        }
        const clock::time_point at = pending_.front().first;
        if (clock::now() < at) {
            l.unlock();
            const auto wait = std::min<clock::duration>(timeout, at - clock::now());
            std::this_thread::sleep_for(wait);
            l.lock();
            if (pending_.empty() || clock::now() < pending_.front().first)
                return std::make_error_code(std::errc::timed_out);
        }
        std::string& front = pending_.front().second;
        n = std::min(cap, front.size());
        std::memcpy(buf, front.data(), n);
        front.erase(0, n);
        if (front.empty()) pending_.pop_front();
        return {};
    }

    void fail_from_now(Fail f) {
        std::lock_guard<std::mutex> l(m_);
        fail = f;
        fail_after = writes_ok;
    }

    std::vector<std::string> attempted;
    std::vector<std::chrono::milliseconds> write_timeouts;
    size_t writes_ok = 0;
    Fail fail = Fail::none;
    size_t fail_after = 0;
    std::map<std::string, std::chrono::milliseconds> reply_delay;
    std::string prompt_error_on;

private:
    std::mutex m_;
    std::deque<std::pair<clock::time_point, std::string>> pending_;
    bool read_error_ = false;
    bool prompt_error_ = false;
};

// Collects warn and error messages while alive.
class WarnCapture {
public:
    WarnCapture() {
        cpsl::radar::set_log_sink([this](cpsl::radar::LogLevel l, const std::string& m) {
            if (l == cpsl::radar::LogLevel::warn || l == cpsl::radar::LogLevel::error) {
                std::lock_guard<std::mutex> lock(m_);
                lines.push_back(m);
            }
        });
    }
    ~WarnCapture() { cpsl::radar::set_log_sink(nullptr); }
    std::vector<std::string> get() {
        std::lock_guard<std::mutex> lock(m_);
        return lines;
    }

private:
    std::mutex m_;
    std::vector<std::string> lines;
};

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

// ---- Part 2: Runner over a fake CLI and a loopback fake DCA1000 ----

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

static int cube_tag(const std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>& c) {
    return c.empty() ? -1 : c[0][0][0].real();
}

TEST_CASE(runner_stop_survives_an_unplugged_cli_and_still_closes_the_bin) {
    const int base = 42000 + static_cast<int>(getpid() % 2000) * 2;
    const int cmd_port = base, data_port = base + 1;
    FakeDca dca("127.0.0.2", cmd_port);
    CHECK(dca.bound);
    if (!dca.bound) return;

    const std::string out = dca_test::tmp_dir() + "/cli_stop_out";
    mkdir(out.c_str(), 0755);
    const std::string cfg = dca_test::write_system_config("cli_stop", out, true, "127.0.0.2", cmd_port, data_port);
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();

    bool threw = false;
    try {
        Runner runner(cfg, fake);
        CHECK(runner.initialized);
        if (!runner.initialized) return;
        CHECK(fake->writes_ok > 5);  // the cfg went through the fake CLI
        runner.start();
        CHECK(dca.saw(0x5));          // RECORD_START

        // stream K frames from the "DCA1000" to the driver's data port
        SystemConfigReader sys(cfg);
        RadarConfigReader radar(sys.getRadarConfigPath());
        const size_t B = radar.get_bytes_per_frame();
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
            CHECK_EQ(cube_tag(runner.get_next_adc_cube(3000)), k + 1);
        }
        close(tx);

        // the radar's USB goes away: sensorStop's write throws
        fake->fail_from_now(FakeCli::Fail::throw_system_error);
        const bool stop_ok = runner.stop();
        CHECK(!stop_ok);
        CHECK_EQ(fake->attempted.back(), std::string("sensorStop\n"));
        CHECK(dca.saw(0x6));          // RECORD_STOP still sent
        struct stat st;
        CHECK(stat((out + "/adc_data.bin").c_str(), &st) == 0);
        CHECK_EQ(static_cast<long long>(st.st_size), static_cast<long long>(K) * static_cast<long long>(B));

        // idempotent: no second sensorStop
        const size_t n = fake->attempted.size();
        CHECK(!runner.stop());
        CHECK_EQ(fake->attempted.size(), n);
    } catch (...) {
        threw = true;  // includes the Runner destructor
    }
    CHECK(!threw);
}

TEST_MAIN()
