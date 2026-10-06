#include "Radar.hpp"

#include <pthread.h>
#include <sched.h>

#include <algorithm>
#include <atomic>
#include <cstring>
#include <exception>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <thread>

#include "CLIController.hpp"
#include "DCA1000Handler.hpp"
#include "SerialStreamer.hpp"

namespace cpsl {
namespace radar {

namespace {

using steady = std::chrono::steady_clock;

int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(steady::now().time_since_epoch()).count();
}

// CLI ports of config_once_per_boot boards configured in this process
std::mutex& once_mutex() {
    static std::mutex m;
    return m;
}
std::set<std::string>& configured_once() {
    static std::set<std::string> s;
    return s;
}

// The DCA worker runs at SCHED_RR 80, as v1's worker did (configurable in core-15).
void raise_worker_priority() {
    sched_param param{};
    param.sched_priority = 80;
    const int r = pthread_setschedparam(pthread_self(), SCHED_RR, &param);
    if (r != 0) {
        log_warn("Radar: could not set the DCA worker thread to SCHED_RR 80: ", std::strerror(r));
    } else {
        log_debug("Radar: DCA worker thread at SCHED_RR 80");
    }
}

}  // namespace

struct Radar::Impl {
    enum State : int { opened, configured, running, stopped };

    explicit Impl(const RadarConfig& c) : cfg(c) {}

    ~Impl() {
        // Radar's destructor already stopped; this only guards the threads
        stop_flag.store(true);
        if (dca_worker.joinable()) dca_worker.join();
        if (serial_worker.joinable()) serial_worker.join();
    }

    RadarConfig cfg;
    CLIController cli;
    DCA1000Handler dca;
    SerialStreamer serial;
    std::shared_ptr<PacketSource> packets;
    bool dca_on = false;
    bool serial_on = false;
    uint32_t stall_ms = 0;

    std::atomic<int> state{opened};
    std::mutex lifecycle;  // configure / start / stop, one at a time
    std::atomic<bool> stop_flag{false};
    std::thread dca_worker;
    std::thread serial_worker;
    bool sensor_started = false;
    std::optional<Status> stop_result;

    std::atomic<int64_t> started_ns{0};
    // the last-frame time a stall was reported for (one report per stall)
    std::atomic<int64_t> dca_stall_reported{-1};
    std::atomic<int64_t> serial_stall_reported{-1};
    std::atomic<uint64_t> stalls{0};
    std::atomic<uint64_t> serial_overwritten{0};

    // a worker thread that ended on an exception (or the serial port's I/O
    // error) leaves its reason here; next_adc_frame / next_point_cloud
    // report it as Code::io_error (core-13 review S8)
    mutable std::mutex fail_m;
    std::string dca_failure, serial_failure;

    void fail_stream(std::string& slot, const std::string& why) {
        log_error("Radar: ", why);
        std::lock_guard<std::mutex> l(fail_m);
        if (slot.empty()) slot = why;
    }
    std::string failure(const std::string& slot) const {
        std::lock_guard<std::mutex> l(fail_m);
        return slot;
    }

    // runs a worker loop body; an exception ends the stream, never the process
    template <class Body>
    void guarded(std::string& slot, const char* what, Body body) {
        try {
            body();
        } catch (const std::exception& e) {
            fail_stream(slot, std::string(what) + " worker stopped: " + e.what());
        } catch (...) {
            fail_stream(slot, std::string(what) + " worker stopped: unknown exception");
        }
    }

    std::string where() const { return cfg.path(); }

    Status stream_state(const char* stream, bool enabled, const std::string& failure_slot) const {
        if (!enabled) return Status(Code::disabled, std::string(stream) + " is not enabled in " + where());
        const int st = state.load();
        if (st == stopped) return Status(Code::stopped, "the radar was stopped");
        if (st != running) return Status(Code::invalid_state, "the radar is not started");
        // stop() has begun (it sets stop_flag first, then wakes the waiters)
        if (stop_flag.load()) return Status(Code::stopped, "the radar is stopping");
        const std::string why = failure(failure_slot);
        if (!why.empty()) return Status(Code::io_error, why);
        return Status::ok();
    }

    // when the stall policy wants next_adc_frame back: the stall deadline of
    // the current gap if it has not been reported yet, else `deadline`
    steady::time_point wake_for_stall(int64_t last_frame_ns, const std::atomic<int64_t>& reported,
                                      steady::time_point deadline) const {
        if (stall_ms == 0) return deadline;
        const int64_t last = std::max(last_frame_ns, started_ns.load());
        if (reported.load() == last) return deadline;  // this gap's stall was already reported
        const steady::time_point at{std::chrono::nanoseconds(last + static_cast<int64_t>(stall_ms) * 1000000)};
        return std::min(deadline, at);
    }

    // true once per stall: no frame of this stream for stall_ms while running
    bool stalled(int64_t last_frame_ns, std::atomic<int64_t>& reported, const char* what) {
        if (stall_ms == 0) return false;
        const int64_t last = std::max(last_frame_ns, started_ns.load());
        if (now_ns() - last < static_cast<int64_t>(stall_ms) * 1000000) return false;
        if (reported.exchange(last) == last) return false;  // this stall was already reported
        stalls.fetch_add(1);
        log_warn("Radar: no ", what, " for ", stall_ms, " ms (runtime.stall_timeout_ms)");
        return true;
    }
};

Radar::Radar(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}

Radar::Radar(Radar&&) noexcept = default;

Radar& Radar::operator=(Radar&& other) noexcept {
    if (this != &other) {
        if (impl_) stop();
        impl_ = std::move(other.impl_);
    }
    return *this;
}

Radar::~Radar() {
    if (impl_) stop();
}

Result<std::unique_ptr<Radar>> Radar::open(const RadarConfig& config) { return open(config, Transports()); }

Result<std::unique_ptr<Radar>> Radar::open(const RadarConfig& config, Transports transports) {
    try {
        set_log_level(config.system().get_log_level());
        std::unique_ptr<Impl> impl(new Impl(config));
        Impl& m = *impl;
        const SystemConfigReader& sys = m.cfg.system();
        m.dca_on = sys.get_dca1000_streaming_enabled();
        m.serial_on = sys.get_serial_streaming_enabled();
        m.stall_ms = sys.get_stall_timeout_ms();

        const Status dir = create_output_dir(sys.get_output_dir());
        if (!dir) return dir;

        if (m.dca_on) {
            // output files (adc_data.bin / LVDS_Raw_0.bin) and frame buffers
            if (!m.dca.configure_pipeline(sys, m.cfg.radar_cfg())) {
                const std::string d = sys.get_output_dir().empty() ? std::string("the current directory")
                                                                   : sys.get_output_dir();
                return Status(Code::file_error, "cannot open the output files in " + d);
            }
            m.packets = transports.packets ? transports.packets : std::make_shared<UdpPacketSource>(sys);
            m.dca.set_packet_source(m.packets);
            const Status s = m.packets->open();
            if (!s) return s;
        }
        if (m.serial_on && !m.serial.initialize(sys)) {
            return Status(Code::open_failed, "cannot open the serial data port " + sys.getRadarDataPort());
        }
        const bool cli_ok = transports.cli ? m.cli.initialize(sys, transports.cli) : m.cli.initialize(sys);
        if (!cli_ok) {
            return Status(Code::open_failed, "cannot open the CLI port " + sys.getRadarCliPort());
        }
        m.cli.set_frame_period_ms(m.cfg.frame_shape().period_ms);
        return std::unique_ptr<Radar>(new Radar(std::move(impl)));
    } catch (const std::exception& e) {
        return Status(Code::open_failed, std::string("Radar::open: ") + e.what());
    } catch (...) {
        return Status(Code::open_failed, "Radar::open: unknown error");
    }
}

Status Radar::configure() {
    if (!impl_) return Status(Code::invalid_state, "moved-from Radar");
    Impl& m = *impl_;
    std::lock_guard<std::mutex> lock(m.lifecycle);
    try {
        const int st = m.state.load();
        if (st == Impl::stopped) return Status(Code::invalid_state, "configure() after stop(): open a new Radar");
        if (st == Impl::running) return Status(Code::invalid_state, "configure() while running: stop() first");

        const BoardDescriptor& board = m.cfg.board();
        const std::string port = m.cfg.system().getRadarCliPort();
        const bool once = board.lifecycle.config_once_per_boot;
        if (once) {
            std::lock_guard<std::mutex> g(once_mutex());
            if (configured_once().count(port) != 0) {
                m.state = Impl::configured;
                return Status(Code::already_configured,
                              "the " + board.name + " on " + port +
                                  " was already configured in this process and accepts a cfg once per "
                                  "power-up: nothing sent");
            }
        }

        if (m.dca_on) {
            const Status s = m.packets->configure();
            if (!s) return s;
        }

        if (once) {
            // any attempt uses up this power-up
            std::lock_guard<std::mutex> g(once_mutex());
            configured_once().insert(port);
        }
        const bool all_done = m.cli.send_config_to_IWR();
        if (m.cli.io_error()) {
            return Status(Code::io_error, "the CLI port " + port + " failed while sending the cfg");
        }
        if (!all_done) {
            if (once) {
                // e.g. the cascade demo cannot be reconfigured once started (TI known issue)
                return Status(Code::config_rejected,
                              "the " + board.name + " did not acknowledge every cfg command. Its demo can only be "
                              "configured once per boot: power-cycle the EVM and try again.");
            }
            m.state = Impl::configured;
            return Status(Code::config_rejected, "not every config command was acknowledged with '" +
                                                     board.cli.ack + "' (see the warnings)");
        }
        m.state = Impl::configured;
        return Status::ok();
    } catch (const std::exception& e) {
        return Status(Code::io_error, std::string("configure: ") + e.what());
    } catch (...) {
        return Status(Code::io_error, "configure: unknown error");
    }
}

Status Radar::start() {
    if (!impl_) return Status(Code::invalid_state, "moved-from Radar");
    Impl& m = *impl_;
    std::lock_guard<std::mutex> lock(m.lifecycle);
    try {
        const int st = m.state.load();
        if (st == Impl::running) return Status::ok();
        if (st == Impl::stopped) return Status(Code::invalid_state, "start() after stop(): open a new Radar");
        if (st != Impl::configured) return Status(Code::invalid_state, "start() before configure()");

        m.stop_flag = false;
        m.started_ns = now_ns();
        m.dca_stall_reported = -1;
        m.serial_stall_reported = -1;

        if (m.dca_on) {
            const Status s = m.packets->start();  // UDP: recordStart, then the RX thread
            if (!s) return s;
            m.dca_worker = std::thread([&m] {
                raise_worker_priority();
                m.guarded(m.dca_failure, "the DCA1000", [&m] {
                    while (!m.stop_flag.load(std::memory_order_relaxed)) {
                        m.dca.process_next_packet();  // waits up to 500 ms for a packet
                    }
                });
                if (!m.failure(m.dca_failure).empty()) m.dca.close_frames();  // wake a waiting consumer
            });
        }
        if (m.serial_on) {
            m.serial_worker = std::thread([&m] {
                m.guarded(m.serial_failure, "the serial data", [&m] {
                    while (!m.stop_flag.load(std::memory_order_relaxed)) {
                        // waits up to data_uart.timeout_ms for a frame
                        if (!m.serial.process_next_message() && m.serial.io_error()) {
                            m.fail_stream(m.serial_failure,
                                          "the serial data port failed; serial streaming stopped");
                            break;
                        }
                    }
                });
            });
        }
        // running from here: stop() now joins the threads and stops the sensor
        m.state = Impl::running;
        m.sensor_started = true;
        if (!m.cli.sendStartCommand()) {
            if (m.cli.io_error()) {
                return Status(Code::io_error, "sensorStart could not be sent on " +
                                                  m.cfg.system().getRadarCliPort() + " (radar disconnected?)");
            }
            log_warn("Radar: sensorStart was not acknowledged with '", m.cfg.board().cli.ack, "'");
        }
        return Status::ok();
    } catch (const std::exception& e) {
        return Status(Code::io_error, std::string("start: ") + e.what());
    } catch (...) {
        return Status(Code::io_error, "start: unknown error");
    }
}

Status Radar::stop() {
    if (!impl_) return Status(Code::invalid_state, "moved-from Radar");
    Impl& m = *impl_;
    // a second caller blocks here until the first has finished, then gets its Status
    std::lock_guard<std::mutex> lock(m.lifecycle);
    if (m.stop_result) return *m.stop_result;

    Status result;
    auto fail = [&result](Status s) {
        if (result) {
            result = std::move(s);
        } else {
            result.message += "; " + s.message;
        }
    };
    // every step runs even if an earlier one failed: the files must still be
    // closed when the radar's USB is gone, and sensorStop must still be tried
    // when the DCA1000 has gone quiet
    try {
        m.stop_flag = true;
        // wake a consumer blocked in next_adc_frame: it sees stop_flag and
        // returns Code::stopped instead of waiting out its timeout
        if (m.dca_on) m.dca.close_frames();
        if (m.dca_worker.joinable()) m.dca_worker.join();
        if (m.serial_worker.joinable()) m.serial_worker.join();

        if (m.dca_on) {
            // packet source (UDP: RX thread, recordStop; unacknowledged = warning),
            // then flush and close adc_data.bin / LVDS_Raw_0.bin
            m.dca.stop();
            if (!m.dca.output_files_ok()) {
                const std::string d = m.cfg.system().get_output_dir();
                fail(Status(Code::file_error, "an output file in " + (d.empty() ? std::string(".") : d) +
                                                  " failed to flush or close"));
            }
        }

        if (m.sensor_started) {
            // an I/O error (radar unplugged) is a failure, a missing ack only a warning
            if (!m.cli.sendStopCommand()) {
                if (m.cli.io_error()) {
                    log_error("Radar: sensorStop could not be sent (radar disconnected?)");
                    fail(Status(Code::io_error, "sensorStop could not be sent on " +
                                                    m.cfg.system().getRadarCliPort() + " (radar disconnected?)"));
                } else {
                    log_warn("Radar: sensorStop was not acknowledged with '", m.cfg.board().cli.ack, "'");
                }
            }
            if (m.cfg.board().lifecycle.config_once_per_boot) {
                log_info("Radar: power-cycle the ", m.cfg.board().name, " EVM before configuring it again");
            }
        }
    } catch (const std::exception& e) {
        fail(Status(Code::io_error, std::string("stop: ") + e.what()));
    } catch (...) {
        fail(Status(Code::io_error, "stop: unknown error"));
    }
    m.state = Impl::stopped;
    m.stop_result = result;
    return result;
}

bool Radar::next_adc_frame(AdcFrame& out, std::chrono::milliseconds timeout, Status* why) {
    auto set = [why](Status s) {
        if (why) *why = std::move(s);
        return false;
    };
    if (!impl_) return set(Status(Code::invalid_state, "moved-from Radar"));
    Impl& m = *impl_;
    const steady::time_point deadline = steady::now() + timeout;
    for (;;) {
        Status st = m.stream_state("dca1000", m.dca_on, m.dca_failure);
        if (!st) return set(std::move(st));
        // block on the frame queue's condition variable (woken by a publish
        // or by stop()), but no longer than the stall policy allows
        const steady::time_point wake = m.wake_for_stall(m.dca.last_frame_ns(), m.dca_stall_reported, deadline);
        uint64_t index = 0;
        size_t missing = 0;
        if (m.dca.take_frame(out.data, index, missing, out.completed_at, wake)) {
            out.index = index;
            out.missing_bytes = static_cast<uint32_t>(missing);
            out.shape = m.cfg.frame_shape();
            if (why) *why = Status::ok();
            return true;
        }
        if (m.stalled(m.dca.last_frame_ns(), m.dca_stall_reported, "ADC frame")) {
            return set(Status(Code::stalled, "no ADC frame for " + std::to_string(m.stall_ms) + " ms"));
        }
        if (steady::now() >= deadline) {
            st = m.stream_state("dca1000", m.dca_on, m.dca_failure);  // woken by stop(): say so
            if (!st) return set(std::move(st));
            return set(Status(Code::timeout, "no ADC frame within the timeout"));
        }
    }
}

bool Radar::next_point_cloud(PointCloud& out, std::chrono::milliseconds timeout, Status* why) {
    auto set = [why](Status s) {
        if (why) *why = std::move(s);
        return false;
    };
    if (!impl_) return set(Status(Code::invalid_state, "moved-from Radar"));
    Impl& m = *impl_;
    const steady::time_point deadline = steady::now() + timeout;
    std::vector<std::vector<float>> points;
    std::vector<std::vector<float>> side;
    for (;;) {
        Status st = m.stream_state("serial_stream", m.serial_on, m.serial_failure);
        if (!st) return set(std::move(st));
        uint32_t frame_number = 0;
        uint64_t overwritten = 0;
        if (m.serial.take_frame(points, side, frame_number, overwritten)) {
            m.serial_overwritten.fetch_add(overwritten);
            out.frame_number = frame_number;
            out.points.resize(points.size());
            for (size_t i = 0; i < points.size(); i++) {
                Point& p = out.points[i];
                const std::vector<float>& r = points[i];
                p.x = r.size() > 0 ? r[0] : 0.0f;
                p.y = r.size() > 1 ? r[1] : 0.0f;
                p.z = r.size() > 2 ? r[2] : 0.0f;
                p.v = r.size() > 3 ? r[3] : 0.0f;
                const bool has_side = i < side.size() && side[i].size() >= 2;
                p.snr_db = has_side ? side[i][0] : 0.0f;
                p.noise_db = has_side ? side[i][1] : 0.0f;
            }
            if (why) *why = Status::ok();
            return true;
        }
        if (m.stalled(m.serial.last_frame_ns(), m.serial_stall_reported, "TLV frame")) {
            return set(Status(Code::stalled, "no TLV frame for " + std::to_string(m.stall_ms) + " ms"));
        }
        const steady::time_point now = steady::now();
        if (now >= deadline) return set(Status(Code::timeout, "no TLV frame within the timeout"));
        std::this_thread::sleep_for(std::min<steady::duration>(std::chrono::milliseconds(5), deadline - now));
    }
}

Stats Radar::stats() const {
    Stats s;
    if (!impl_) return s;
    Impl& m = *impl_;
    if (m.dca_on) {
        const DCA1000Handler::Stats d = m.dca.get_stats();
        s.packets = d.assembler.received_packets;
        s.dropped = d.assembler.dropped_packets;
        s.drop_events = d.assembler.dropped_packet_events;
        s.late = d.assembler.late_packets;
        s.duplicate = d.assembler.duplicate_packets;
        s.incomplete_frames = d.assembler.incomplete_frames;
        s.skipped_frames = d.assembler.skipped_frames;
        s.frames = d.frames;
        s.frames_overwritten = d.frames_overwritten;
        if (m.packets) {
            s.rx_overrun = m.packets->overrun_count();
            s.rcvbuf_bytes = m.packets->rcvbuf_bytes();
        }
    }
    if (m.serial_on) {
        s.serial_frames = m.serial.get_committed_frame_count();
        s.serial_missed = m.serial.get_missed_frame_count();
        s.serial_overwritten = m.serial_overwritten.load();
    }
    s.stalls = m.stalls.load();
    return s;
}

const RadarConfig& Radar::config() const { return impl_->cfg; }

bool Radar::dca1000_enabled() const { return impl_ && impl_->dca_on; }

bool Radar::serial_enabled() const { return impl_ && impl_->serial_on; }

}  // namespace radar
}  // namespace cpsl
