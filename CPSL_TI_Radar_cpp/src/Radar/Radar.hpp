#ifndef CPSL_RADAR_RADAR_HPP
#define CPSL_RADAR_RADAR_HPP

// The driver's public API (driver v2 design §3):
//
//   auto cfg   = cpsl::radar::RadarConfig::load("system.json");   // Result<RadarConfig>
//   auto radar = cpsl::radar::Radar::open(*cfg);                  // Result<unique_ptr<Radar>>
//   (*radar)->configure();  (*radar)->start();
//   cpsl::radar::AdcFrame f;
//   while ((*radar)->next_adc_frame(f, std::chrono::milliseconds(500))) { ... }
//   (*radar)->stop();
//
// No call throws, exits or prints: failures come back as a Status, and
// messages go to the log sink (Log.hpp) at runtime.log_level.

#include <chrono>
#include <complex>
#include <cstdint>
#include <memory>
#include <vector>

#include "ByteStream.hpp"
#include "Log.hpp"
#include "PacketSource.hpp"
#include "RadarConfig.hpp"
#include "Status.hpp"
#include "UartFrame.hpp"

namespace cpsl {
namespace radar {

// One raw-ADC frame from the DCA1000. `data` is indexed [rx][sample][chirp],
// as in v1 (design D5). next_adc_frame swaps a pooled buffer into `data`
// (no copy) and the buffer `data` held goes back to the driver's pool, so
// keep reusing the same AdcFrame: after the first frames nothing is
// allocated per frame.
struct AdcFrame {
    uint64_t index = 0;                                 // stream offset / bytes per frame
    std::chrono::steady_clock::time_point completed_at;  // when the last byte was placed
    uint32_t missing_bytes = 0;                          // zero-filled bytes (lost packets)
    FrameShape shape;
    std::vector<std::vector<std::vector<std::complex<int16_t>>>> data;  // [rx][sample][chirp]
};

// One frame of the on-chip demo's TLV stream. Point (x, y, z, v, snr_db,
// noise_db) is defined in UartFrame.hpp; which fields a board's demo fills
// depends on its data_uart.tlv_dialect (docs/ARCHITECTURE.md). Like
// AdcFrame, next_point_cloud swaps the driver's buffer into `points`, so
// reusing one PointCloud allocates nothing after the first frames.
struct PointCloud {
    uint32_t frame_number = 0;                           // the demo's frame counter
    std::chrono::steady_clock::time_point completed_at;  // when the frame's last byte was read
    std::vector<Point> points;
};

// Counters since start(). The DCA1000 counters are the FrameAssembler's,
// sampled at each completed frame and at stop(); see docs/ARCHITECTURE.md.
struct Stats {
    // DCA1000 path
    uint64_t packets = 0;             // newest packet sequence number seen
    uint64_t dropped = 0;             // packets never received (net of late fills)
    uint64_t drop_events = 0;         // forward sequence gaps
    uint64_t late = 0;                // packets that arrived after a newer one
    uint64_t duplicate = 0;           // packets received twice
    uint64_t incomplete_frames = 0;   // frames completed with zero-filled bytes
    uint64_t skipped_frames = 0;      // frames with no byte received (never completed)
    uint64_t rx_overrun = 0;          // packets discarded in user space (RX ring full): 0 since core-15
    uint64_t rx_ring_full = 0;        // times the RX ring was full and the RX thread stopped reading
    uint64_t kernel_drops = 0;        // packets the kernel dropped (SO_RCVBUF full; SO_RXQ_OVFL)
    uint64_t frames = 0;              // frames completed (and saved, when saving)
    uint64_t frames_overwritten = 0;  // completed frames dropped from a full frame queue before next_adc_frame took them
    uint64_t rcvbuf_bytes = 0;        // SO_RCVBUF granted by the kernel
    // serial TLV path
    uint64_t serial_frames = 0;       // valid TLV frames received
    uint64_t serial_missed = 0;       // gaps in the demo's frame counter
    uint64_t serial_overwritten = 0;  // TLV frames replaced before next_point_cloud took them
    // both
    uint64_t stalls = 0;              // runtime.stall_timeout_ms episodes (see next_adc_frame)
};

// Optional transports for Radar::open: a null member means the real one
// (the CLI serial port named by cli.port; the DCA1000 over UDP; the serial
// data port named by serial_stream.port).
struct Transports {
    std::shared_ptr<ByteStream> cli;
    std::shared_ptr<PacketSource> packets;
    std::shared_ptr<ByteStream> data = nullptr;
};

class Radar {
public:
    // Open the ports and sockets the config enables and the output files, and
    // create output.dir. Sends nothing to the radar or the DCA1000. Also sets
    // the process-wide log level to runtime.log_level.
    static Result<std::unique_ptr<Radar>> open(const RadarConfig& config);
    static Result<std::unique_ptr<Radar>> open(const RadarConfig& config, Transports transports);

    Radar(const Radar&) = delete;
    Radar& operator=(const Radar&) = delete;
    Radar(Radar&&) noexcept;
    Radar& operator=(Radar&&) noexcept;  // stops the radar being replaced
    ~Radar();                            // stop()

    // Configure the DCA1000 (when enabled), then send the radar cfg. On a
    // board with lifecycle.config_once_per_boot, a second call in this
    // process (for the same CLI port) sends nothing and returns
    // Code::already_configured; start() is still allowed after it.
    // Code::config_rejected: a cfg command was not acknowledged.
    Status configure();
    // DCA1000 recordStart and its threads, the serial reader, then the
    // sensor start command. Idempotent while running; invalid after stop().
    Status start();
    // Stop everything and close the output files. Idempotent and safe from
    // several threads: a second caller waits for the first and gets the
    // same Status. Code::io_error: sensorStop could not be sent (radar gone);
    // Code::file_error: an output file failed to flush. A missing
    // acknowledgement is only a warning.
    Status stop();

    // Wait at most `timeout` for the next completed frame (blocking on a
    // condition variable: it returns as soon as the frame is published).
    // false: none, and `why` (if given) says why: Code::timeout,
    // Code::stalled (no frame for runtime.stall_timeout_ms; reported once per
    // stall, with a warning and Stats::stalls + 1), Code::stopped (also when
    // stop() is called while waiting), Code::io_error (the stream's worker
    // thread ended on an exception or a port error; the message says why;
    // the process is never terminated), Code::invalid_state (not started) or
    // Code::disabled (stream off in the config). Completed frames wait in a
    // drop-oldest queue of runtime.frame_queue_depth frames (default 4; 1 =
    // the latest frame wins); a frame dropped because the queue was full is
    // counted in frames_overwritten. Frames come out in order, each once.
    bool next_adc_frame(AdcFrame& out, std::chrono::milliseconds timeout, Status* why = nullptr);
    // The same for the serial TLV stream, except that only the latest
    // frame waits (a frame replaced before it was taken counts in
    // serial_overwritten). A frame is published as soon as its last byte
    // is read (core-16).
    bool next_point_cloud(PointCloud& out, std::chrono::milliseconds timeout, Status* why = nullptr);

    Stats stats() const;
    const RadarConfig& config() const;
    bool dca1000_enabled() const;
    bool serial_enabled() const;

    struct Impl;

private:
    explicit Radar(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> impl_;
};

}  // namespace radar
}  // namespace cpsl

#endif
