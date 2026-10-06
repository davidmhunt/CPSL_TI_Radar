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
// Plausibility and resync (core-11 review S1, directive core-15). Once the
// stream has started, a packet is implausible when
//   - ahead:  its byte count is more than the window W past the end of the
//     furthest payload, beyond what its sequence number explains (each
//     sequence number it moves on allows one more payload of the largest
//     size placed so far); its payload
//     is discarded and counted in implausible_packets, or
//   - behind: its whole payload lies more than W before the oldest open
//     frame (late, as today: counted and dropped).
// W (kResyncWindowFrames) is one frame. A lone implausible packet (one wild
// byte count) costs only its own payload. kResyncPackets (4) consecutive
// implausible packets whose payloads follow each other byte for byte (a
// DCA1000 restart that sends the count back to 0, or the stream left behind
// by a wild count that was accepted) trigger a resync: the open frames are
// dropped (counted in skipped_frames), assembly and sequence tracking restart
// at the first of those packets, they are replayed, and resyncs goes up by
// one. The first new frame is whole when the restart's first packets arrive
// in order. Frame indices keep increasing across a resync (they continue
// after the dropped frames), so after one an index is no longer byte
// offset / bytes_per_frame.
//
// Documented compromise, accepted by the user 2026-10-06: a restart is detected
// only once its packets lie more than W behind the oldest open frame, so not
// before the old stream is about two frames in (a restart in the first 64
// packets also looks like sequence duplicates, which never count toward a
// resync). Inside that window there is no resync: one emitted frame mixes
// old and new bytes with missing_bytes 0, and one new-stream frame is lost.
// Conversely, a contiguous run of >= 4 genuinely late packets more than a
// frame late, or re-delivered duplicates older than 64 packets, look like a
// restart: they trigger a resync (open frames dropped, dropped_packets grows
// by the sequence distance). Neither occurs on a direct DCA1000 link.
//
// Nothing here logs or prints: the counters are read with get_stats() (the
// driver logs them periodically at debug level and in Radar::stats(), and
// warns on a resync).
//
// Sequence numbers give the packet counters: a forward gap counts its
// packets as dropped and is one drop event; a packet older than the newest
// one is either a duplicate (already seen) or late (it fills an earlier gap,
// so dropped_packets goes back down by one, and once every packet of a gap
// has arrived late the gap's drop event is taken back: a reorder is not a
// drop). A 64-packet window tells the two apart; an older packet counts as
// late without changing dropped_packets or the events.
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
        uint32_t dropped_packet_events = 0;  // forward sequence gaps not (yet) filled by late packets
        uint64_t adc_data_byte_count   = 0;  // end of the furthest payload seen (stream offset)
        uint32_t late_packets          = 0;  // arrived after a newer packet (not a duplicate)
        uint32_t duplicate_packets     = 0;  // sequence number already received
        uint32_t incomplete_frames     = 0;  // emitted with missing (zero) bytes
        uint32_t skipped_frames        = 0;  // never emitted: no byte received, or dropped by a resync
        uint32_t implausible_packets   = 0;  // byte count implausibly far ahead: payload discarded
        uint32_t resyncs               = 0;  // assembly restarted on a new byte count (see above)
    };

    // called once per emitted frame: bytes, frame index (stream offset / bytes_per_frame),
    // number of missing (zero-filled) bytes
    using FrameSink = std::function<void(const std::vector<uint8_t>& frame, uint64_t index, size_t missing_bytes)>;

    // Default reorder slack used by the driver, in packets of payload.
    static constexpr size_t kDefaultReorderSlackPackets = 8;
    // consecutive, byte-contiguous implausible packets that trigger a resync
    static constexpr size_t kResyncPackets = 4;
    // plausibility window W, in frames
    static constexpr size_t kResyncWindowFrames = 1;

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
    uint32_t resync_count() const { return stats_.resyncs; }
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
    // the open gaps inside the window: sequence numbers [first, last], `missing`
    // of them not arrived; a gap filled completely takes back its drop event
    struct Gap {
        uint32_t first, last, missing;
    };
    static constexpr size_t kMaxGaps = 32;  // a 64-packet window holds at most 32 gaps
    Gap gaps_[kMaxGaps];
    size_t gap_n_ = 0;
    void open_gap(uint32_t first, uint32_t last);
    void fill_gap(uint32_t seq);

    // resync: emitted index = frame number (byte offset / B) + index_bias_
    uint64_t index_bias_ = 0;
    bool rebase_pending_ = false;  // set index_bias_ when assembly restarts
    uint64_t next_index_ = 0;      // the index the first frame after a resync gets
    // the current run of implausible packets (copies, kept for the replay)
    struct Held {
        std::vector<uint8_t> bytes;
        bool counted_late = false;         // late_packets was incremented for it
        bool counted_implausible = false;  // implausible_packets was incremented for it
    };
    std::vector<Held> run_;      // kResyncPackets entries, capacity kept
    std::vector<Held> replay_;   // swapped with run_ for the replay
    size_t run_n_ = 0;
    uint64_t run_end_ = 0;       // stream offset just past the run's last payload
    uint64_t max_payload_ = 0;   // largest payload placed (a short last packet must not shrink the allowance)

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
    // place a plausible packet's payload (the core-11 P1 path)
    int place(const uint8_t* payload, uint64_t first, uint64_t end, SeqKind kind);
    // add an implausible packet to the run (or start a new run); resync at kResyncPackets
    int hold(const uint8_t* data, int len, uint64_t first, uint64_t end, bool late, bool implausible);
    int resync();
};

#endif // FRAMEASSEMBLER_H
