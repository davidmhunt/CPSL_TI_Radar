#ifndef SERIALSTREAMER
#define SERIALSTREAMER

// SerialStreamer: reads the on-chip demo's TLV frames from the serial data
// port and publishes each one as soon as its last byte has arrived
// (directive core-16, P8).
//
// Framing is length-driven: find the magic word, read the header, then read
// exactly the rest of totalPacketLen, and only then parse (parse_uart_frame,
// UartFrame.hpp) and publish. The next frame's magic word is never waited
// for. Bytes before a magic word are discarded; a frame that fails
// validation is dropped with a warning and the search resumes just past its
// magic word.
//
// The port is a cpsl::radar::ByteStream: the serial port in the driver, a
// fake in tests. Buffers are reused: after the first frames, reading,
// parsing and publishing a frame allocates nothing.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <fstream>
#include <memory>
#include <mutex>
#include <vector>

#include "ByteStream.hpp"
#include "SystemConfigReader.hpp"
#include "UartFrame.hpp"

class SerialStreamer {

public:
    using clock = std::chrono::steady_clock;

    SerialStreamer() = default;
    SerialStreamer(const SerialStreamer &) = delete;
    SerialStreamer & operator=(const SerialStreamer &) = delete;
    ~SerialStreamer() = default;

    //opens the serial data port named by the system config
    bool initialize(const SystemConfigReader & systemConfigReader);
    //uses an already open stream (tests: a fake ByteStream)
    bool initialize(const SystemConfigReader & systemConfigReader,
                    std::shared_ptr<cpsl::radar::ByteStream> stream);

    //Read until one valid frame has been published (true), or
    //data_uart.timeout_ms passes, close() is called or the port fails (false;
    //io_error() tells the last apart). Bytes of a frame still in flight when
    //it returns false are kept for the next call.
    bool process_next_message(void);

    //Wait until `wait_until` for a frame not taken yet. On true, its points
    //are swapped into `points` (the vector passed in is kept for reuse, so
    //nothing is copied or allocated), with its frame number, the time its
    //last byte was read, and `overwritten`: frames published since the last
    //take and never taken. False on timeout or after close().
    bool take_frame(std::vector<cpsl::radar::Point> & points,
                    uint32_t & frame_number,
                    clock::time_point & completed_at,
                    uint64_t & overwritten,
                    clock::time_point wait_until);

    //Ends a process_next_message() in progress (within about 100 ms) and
    //wakes take_frame() waiters. For stop().
    void close(void);

    uint32_t get_latest_frame_number(void);
    //frames skipped: gaps in the demo's frame counter since initialize()
    uint32_t get_missed_frame_count(void);
    //frames validated and published since initialize()
    uint64_t get_committed_frame_count(void);
    //frames dropped by parse_uart_frame (or with an impossible totalPacketLen)
    uint64_t get_rejected_frame_count(void) const { return rejected_frames_.load(std::memory_order_relaxed); }
    //steady_clock time (ns since epoch) of the last published frame; 0 = none yet
    int64_t last_frame_ns(void) const { return last_frame_ns_.load(std::memory_order_relaxed); }
    //true if the last read of the data port failed with an error other than a timeout
    bool io_error(void) const { return io_error_.load(std::memory_order_relaxed); }

    bool initialized = false;

private:
    //Read up to `want` more bytes into rx_ (one read_some, at most 100 ms so
    //close() is seen). False on deadline, close() or a port error.
    bool read_more(size_t want, clock::time_point deadline);
    //the body of process_next_message (which flushes the raw-byte file after it)
    bool process_next_message_impl(void);
    //output.save_serial_bytes: append what read_more just read (reader thread)
    void write_raw(const uint8_t * data, size_t n);
    //drop the first n bytes of rx_
    void discard(size_t n);
    //publish work_ (swaps its points with the published buffer)
    void commit(clock::time_point completed_at);

    SystemConfigReader system_config_reader;
    std::shared_ptr<cpsl::radar::ByteStream> stream_;
    cpsl::radar::TlvDialect dialect_ = cpsl::radar::TlvDialect::sdk3;
    size_t header_bytes_ = 40;
    int timeout_ms_ = 1000;

    //receive buffer: rx_[0, rx_len_) holds bytes read but not consumed yet
    std::vector<uint8_t> rx_;
    size_t rx_len_ = 0;
    bool synced_ = false;  //a frame was published: bytes skipped from here on are a resync
    bool warned_compact_ = false;  //the cascade compact-points warning was logged
    cpsl::radar::UartFrame work_;  //the frame being parsed (reader thread only)

    //the published frame and the counters, under m_
    std::mutex m_;
    std::condition_variable cv_;
    std::vector<cpsl::radar::Point> published_points_;
    uint32_t published_frame_number_ = 0;
    clock::time_point published_at_;
    uint64_t committed_frames_ = 0;
    uint64_t taken_at_ = 0;
    bool have_previous_frame_ = false;
    uint32_t previous_frame_number_ = 0;
    uint32_t missed_frame_count_ = 0;

    //output.save_serial_bytes: serial_data.bin, written on the reader thread
    //through a buffered stream; a write error warns once and stops writing
    std::ofstream raw_out_;
    std::vector<char> raw_buf_;
    bool raw_failed_ = false;

    std::atomic<bool> closed_{false};
    std::atomic<int64_t> last_frame_ns_{0};
    std::atomic<bool> io_error_{false};
    std::atomic<uint64_t> rejected_frames_{0};
};

#endif
