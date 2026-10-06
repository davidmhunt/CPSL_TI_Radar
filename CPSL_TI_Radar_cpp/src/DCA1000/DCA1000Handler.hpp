#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <atomic>
#include <chrono>
#include <fstream>
#include <vector>
#include <complex>
#include <memory>
#include <mutex>
#include <condition_variable>
#include <functional>

#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "ADCCubeConverter.hpp"
#include "FrameAssembler.hpp"
#include "PacketSource.hpp"

/**
 * @brief The DCA1000 raw-ADC path: packets from a cpsl::radar::PacketSource
 * (the DCA1000 over UDP, or a replay) are assembled into frames
 * (FrameAssembler), converted to the [rx][sample][chirp] cube
 * (ADCCubeConverter), published to the consumer and written to
 * adc_data.bin / LVDS_Raw_0.bin. This class is the only writer of those files.
 *
 * Frame buffers (design P2): the cubes are a pool of nested
 * [rx][sample][chirp] buffers that are reused and swapped, never copied. The
 * worker converts each frame in place into its work buffer, then swaps that
 * buffer into the next slot of the frame queue (the slot's old buffer becomes
 * the next work buffer). take_frame() swaps the oldest queued buffer with the
 * caller's, so the caller's previous buffer goes back to the pool.
 *
 * Frame queue (design P7, D10): a drop-oldest single-producer queue of
 * runtime.frame_queue_depth slots (default 4; 1 = the latest frame wins).
 * When it is full, publishing drops the oldest untaken frame and counts it in
 * Stats::frames_overwritten. A consumer waiting in take_frame() is woken by a
 * condition variable after the frame is in the queue (no polling);
 * close_frames() wakes it for good. The pool holds depth + 1 buffers (the
 * queue slots and the work buffer), allocated in configure_pipeline().
 */
class DCA1000Handler {
//variables
public:
    using Cube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>;

    //counters, snapshotted when each frame is published and at stop()
    struct Stats {
        FrameAssembler::Stats assembler;
        uint64_t frames = 0;              //frames completed (and written, when saving)
        uint64_t frames_overwritten = 0;  //published frames replaced before a consumer took them
    };

private:

    //guards the published slots (queue_, head_, count_, closed_) and stats_ together
    std::mutex frame_mutex;
    //signalled after a frame is published (under no lock) and by close_frames()
    std::condition_variable frame_cv_;
    bool closed_ = false;

    //tests only: runs after a frame is converted, before it is published
    std::function<void()> publish_hook_;

    bool output_files_ok_ = true;

    //system configuration information
    SystemConfigReader system_config_reader;

    //radar configuration information
    RadarConfigReader radar_config_reader;

    //where packets come from (UdpPacketSource unless one is given)
    std::shared_ptr<cpsl::radar::PacketSource> source_;

    //processing udp data packets
    size_t udp_packet_size;

    //frame tracking (packet/drop stats are owned by assembler_)
    std::uint32_t received_frames;
    std::uint64_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;
    size_t num_rx_channels;

    //saving to files (output.save_adc_frames / output.save_raw_lvds)
    bool save_adc_frames;
    bool save_raw_lvds;
    std::shared_ptr<std::ofstream> adc_cube_out_file;
    std::shared_ptr<std::ofstream> raw_lvds_out_file;
    //the frame in adc_data.bin order, rebuilt per frame (worker thread only)
    std::vector<std::int16_t> file_frame_;

    //one pooled frame buffer and the frame it holds
    struct Slot {
        Cube cube;                 //indexed by [Rx channel, sample, chirp]
        uint64_t index = 0;        //stream offset / bytes_per_frame
        size_t missing = 0;        //zero-filled bytes
        std::chrono::steady_clock::time_point completed_at{};
    };
    //the frame being converted (worker thread only)
    Slot work_;
    //the frame queue: a ring of runtime.frame_queue_depth slots, oldest
    //queued frame at head_, count_ queued (under frame_mutex). Slots outside
    //[head_, head_ + count_) hold free buffers.
    std::vector<Slot> queue_;
    size_t head_ = 0;
    size_t count_ = 0;
    Stats stats_;
    //steady_clock time (ns since its epoch) of the last completed frame; 0 = none yet
    std::atomic<int64_t> last_frame_ns_{0};
    //when the debug status line was last logged (at most one per kStatusPeriod)
    std::chrono::steady_clock::time_point last_status_{};

    //ADC cube conversion (interleaved / non-interleaved)
    ADCCubeConverter converter_;

    //frame assembly (sequence checking, drop detection, frame buffering)
    FrameAssembler assembler_;

//functions
public:
    //the debug-level counter line is logged at most this often (never per packet or per frame)
    static constexpr std::chrono::seconds kStatusPeriod{1};

    DCA1000Handler();
    DCA1000Handler(const DCA1000Handler & rhs) = delete;
    DCA1000Handler & operator=(const DCA1000Handler & rhs) = delete;
    ~DCA1000Handler();

    //configs, output files and frame buffers only: no socket, no DCA1000
    //commands (Radar::open calls it before opening the packet source)
    bool configure_pipeline(const SystemConfigReader& configReader,
                            const RadarConfigReader& radarConfigReader);

    //the source process_next_packet() pops from; the caller (Radar) opens,
    //configures and starts it, and stop() stops it
    void set_packet_source(std::shared_ptr<cpsl::radar::PacketSource> source);
    const std::shared_ptr<cpsl::radar::PacketSource>& packet_source() const { return source_; }

    //assemble one raw DCA1000 UDP packet (what process_next_packet() pops)
    void ingest_packet(const uint8_t* data, int len);

    //tests only: called between converting a frame and publishing it
    void set_publish_hook(std::function<void()> hook);

    //end of a capture: stop the packet source (UDP: RX thread, then
    //recordStop), then flush and close the output files. Call it after the
    //thread running process_next_packet() has been joined. Idempotent; never throws.
    //Returns false if the source did not stop cleanly or a file failed to flush.
    bool stop();
    //false if flushing/closing an output file failed in stop()
    bool output_files_ok() const { return output_files_ok_; }

    //take the packets the source has (up to PacketSource::kMaxBatch, waiting
    //up to 500 ms for the first) and ingest them in place; false if none arrived
    bool process_next_packet();

    //true if a frame is queued for take_frame()
    bool check_new_frame_available();
    //frames in the queue now
    size_t queued_frames();
    //the oldest queued frame, waiting until `deadline` for one: swapped into
    //`out` (no copy; the buffer `out` held goes back to the pool) with its
    //index, missing (zero-filled) byte count and completion time. false: no
    //frame by the deadline, or close_frames() was called.
    bool take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                    std::chrono::steady_clock::time_point& completed_at,
                    std::chrono::steady_clock::time_point deadline);
    //the same without waiting
    bool take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                    std::chrono::steady_clock::time_point& completed_at);
    //wake every waiting take_frame() and make later calls return false at
    //once (Radar::stop, or a failed worker). Idempotent.
    void close_frames();
    Stats get_stats();
    //steady_clock time (ns since epoch) of the last completed frame; 0 = none yet
    int64_t last_frame_ns() const { return last_frame_ns_.load(std::memory_order_relaxed); }

private:

    //receiving data / initializing buffers
    void init_buffers();
    void print_status();

    //processing frame byte buffer
    void save_frame_byte_buffer(uint64_t index, size_t missing_bytes);

    //handling files
    bool init_out_file();
    //append the completed frame to adc_data.bin with one write (design P9)
    void write_adc_frame_to_file();
    bool close_output_files();
};

#endif // DCA1000_H
