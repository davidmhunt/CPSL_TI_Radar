#ifndef CPSL_RADAR_LIVETAP_HPP
#define CPSL_RADAR_LIVETAP_HPP

// Live tap (gui-36): an optional feed of the run's point clouds (and, every
// K-th, ADC frames) to a file descriptor the parent process handed over
// (`--tap-fd N`, a pipe's write end). It exists for the GUI; nothing else
// reads it. Wire format, per message:
//     u32 len (little endian; bytes after this field), u8 type, payload
//   type 1 hello   JSON {"version":1,"board":..,"streams":[..],"adc_every":K}   first, once
//   type 2 points  JSON {"type":"frame","frame":N,"n":N,"t":unix_s,"pts":[[x,y,z,v,snr,noise],..]}
//                  (NaN / inf -> null)
//   type 3 adc     one JSON header line {"index","shape":[rx,samples,chirps],"missing_bytes",
//                  "layout":"rx,sample,chirp","iq_order":"IQ"} + "\n" + int16 I,Q pairs
//                  flattened [rx][sample][chirp] (little endian)
// The tap never slows the run: push_* encode on the caller's thread into a
// one-slot "latest wins" mailbox per kind and return; a writer thread does the
// (possibly blocking) writes. A message replaced before the writer took it is
// counted in skipped(). A write error (EPIPE: the reader went away) logs one
// warning and disables the tap; the run continues. SIGPIPE is ignored
// process-wide once a tap is started.

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "Radar.hpp"

namespace cpsl {
namespace radar {
namespace livetap {

// Pure encoders: each returns the whole message, length prefix included.
std::vector<uint8_t> encode_hello(const std::string& board, bool points, bool adc, uint32_t adc_every);
std::vector<uint8_t> encode_points(const PointCloud& cloud, double unix_time_s);
std::vector<uint8_t> encode_adc(const AdcFrame& frame);

}  // namespace livetap

class LiveTap {
public:
    // fd: the pipe's write end (owned; closed by the destructor). adc_every 0 = no ADC messages.
    LiveTap(int fd, uint32_t adc_every);
    ~LiveTap();
    LiveTap(const LiveTap&) = delete;
    LiveTap& operator=(const LiveTap&) = delete;

    // Ignores SIGPIPE, queues the hello message and starts the writer thread.
    void start(const std::string& board, bool points, bool adc);
    // Join the writer (a write blocked on a full pipe is abandoned within ~100 ms). Idempotent.
    void stop();

    // Never block. No-ops once the tap is disabled.
    void push_points(const PointCloud& cloud);
    // Sends the 0th, K-th, 2K-th ... frame passed in (K = adc_every); the rest are ignored.
    void offer_adc(const AdcFrame& frame);

    bool enabled() const { return !disabled_.load(); }
    uint64_t sent() const { return sent_.load(); }          // points messages written
    uint64_t adc_sent() const { return adc_sent_.load(); }  // adc messages written
    uint64_t skipped() const { return skipped_.load(); }    // points or adc messages replaced unsent
    // "stats v1 tap t=<s> sent=<n> skipped=<n> adc_sent=<n>\n"
    std::string stats_line(double t) const;

private:
    void run();
    bool write_all(const std::vector<uint8_t>& msg);
    void disable(const std::string& why);

    int fd_;
    uint32_t adc_every_;
    uint64_t adc_seen_ = 0;
    std::thread writer_;
    std::mutex m_;
    std::condition_variable cv_;
    bool stopping_ = false;
    std::vector<uint8_t> hello_, points_, adc_;  // slots; empty = nothing waiting
    std::atomic<bool> disabled_{false};
    std::atomic<bool> stop_flag_{false};
    std::atomic<uint64_t> sent_{0}, adc_sent_{0}, skipped_{0};
};

}  // namespace radar
}  // namespace cpsl

#endif
