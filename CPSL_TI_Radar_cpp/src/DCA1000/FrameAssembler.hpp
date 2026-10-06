#ifndef FRAMEASSEMBLER_H
#define FRAMEASSEMBLER_H

// Assembles raw DCA1000 UDP packets into complete radar frames.
//
// Packet = 10-byte header (uint32 LE sequence number, uint48 LE count of ADC
// bytes sent BEFORE this packet) + ADC payload. The byte count places every
// payload byte: stream offset o belongs to frame o / bytes_per_frame at
// position o % bytes_per_frame. push_packet() copies each payload (split at a
// frame boundary when it straddles one) straight to that position with
// memcpy, so a lost, late or duplicated packet can never shift later bytes.
//
// At most two frames are open at once (the oldest and the next). A frame is
// emitted when
//   - every one of its bytes has arrived, or
//   - the stream has moved reorder_slack_bytes past its end (its missing
//     bytes are zero; with slack 0 that is as soon as its last byte position
//     has been reached).
// A frame with no bytes at all is not emitted; it is counted in
// skipped_frames. Data for a frame that was already emitted is late: it is
// counted and dropped.
//
// Nothing here logs or prints: the counters are read with get_stats() (the
// driver logs them periodically at debug level and in Radar::stats()).
//
// Sequence numbers give the packet counters: a forward gap counts its
// packets as dropped (one drop event per gap); a packet older than the newest
// one is either a duplicate (already seen) or late (it fills an earlier gap,
// so dropped_packets goes back down by one). A 64-packet window tells the two
// apart; an older packet counts as late without changing dropped_packets.
//
// Frames are delivered through the frame sink (set_frame_sink), once each,
// in order. Without a sink, get_frame_bytes() returns the most recently
// emitted frame; it is valid until the next push_packet()/flush() call, and
// when one call emits several frames only the last one is available.

#include <cstddef>
#include <cstdint>
#include <functional>
#include <utility>
#include <vector>

class FrameAssembler {
public:
    struct Stats {
        uint32_t received_packets      = 0;  // newest sequence number seen
        uint32_t dropped_packets       = 0;  // sequence numbers never received (net of late fills)
        uint32_t dropped_packet_events = 0;  // forward sequence gaps
        uint64_t adc_data_byte_count   = 0;  // end of the furthest payload seen (stream offset)
        uint32_t late_packets          = 0;  // arrived after a newer packet (not a duplicate)
        uint32_t duplicate_packets     = 0;  // sequence number already received
        uint32_t incomplete_frames     = 0;  // emitted with missing (zero) bytes
        uint32_t skipped_frames        = 0;  // no byte received: never emitted
    };

    // called once per emitted frame: bytes, frame index (stream offset / bytes_per_frame),
    // number of missing (zero-filled) bytes
    using FrameSink = std::function<void(const std::vector<uint8_t>& frame, uint64_t index, size_t missing_bytes)>;

    // Default reorder slack used by the driver, in packets of payload.
    static constexpr size_t kDefaultReorderSlackPackets = 8;

    // reorder_slack_bytes is clamped below bytes_per_frame.
    void configure(size_t bytes_per_frame, size_t reorder_slack_bytes = 0);

    void set_frame_sink(FrameSink sink);

    // Process one raw DCA1000 UDP packet (includes the 10-byte header).
    // Returns the number of frames emitted (usually 0 or 1), 0 for a packet
    // with no payload, or -1 if configure() has not been called.
    int push_packet(const uint8_t* data, int len);

    // End of stream: emit every open frame that holds data. Returns the number emitted.
    int flush();

    // The most recently emitted frame and its index.
    const std::vector<uint8_t>& get_frame_bytes() const;
    uint64_t get_frame_index() const;

    Stats get_stats() const;
    // Zero the counters; frame assembly state is kept. The next sequence
    // number is compared against 0 again.
    void reset_stats();

private:
    struct Slot {
        std::vector<uint8_t> bytes;
        std::vector<std::pair<size_t, size_t>> have;  // received [begin, end), sorted, disjoint
    };

    size_t bytes_per_frame_ = 0;
    size_t slack_           = 0;
    FrameSink sink_;

    Slot slots_[2];               // frame f lives in slots_[f % 2]
    bool started_    = false;     // base_ is valid
    uint64_t base_   = 0;         // oldest open frame
    uint64_t front_  = 0;         // end of the furthest payload placed (stream offset)
    std::vector<uint8_t> completed_frame_;
    uint64_t completed_index_ = 0;

    // sequence tracking
    bool have_seq_       = false;
    uint32_t newest_seq_ = 0;
    uint64_t seq_window_ = 0;     // bit i: newest_seq_ - i was received

    Stats stats_;

    static uint32_t parse_sequence_number(const uint8_t* data);
    static uint64_t parse_byte_count(const uint8_t* data);

    enum class SeqKind { in_order, late, duplicate };
    SeqKind track_sequence(uint32_t seq);

    Slot& slot(uint64_t frame) { return slots_[frame & 1]; }
    static void add_range(Slot& s, size_t begin, size_t end);
    bool complete(const Slot& s) const;
    // emit (or skip, if empty) base_, then advance it
    int close_base();
};

#endif // FRAMEASSEMBLER_H
