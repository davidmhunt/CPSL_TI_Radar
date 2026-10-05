// FrameAssembler: DCA1000 UDP packet -> frame assembly, drop detection.
//
// Packet = 10-byte header (uint32 LE sequence number, uint48 LE byte count of
// ADC bytes sent BEFORE this packet) + ADC payload. Sequence numbers start at
// 1. The synthetic stream byte at offset `o` is pattern(o), never 0, so
// zero padding is distinguishable from data.
#include "test_harness.hpp"
#include "FrameAssembler.hpp"

typedef std::vector<uint8_t> Bytes;

static uint8_t pattern(uint64_t o) { return static_cast<uint8_t>(o % 251 + 1); }

// packet carrying stream bytes [offset, offset + len)
static Bytes make_packet(uint32_t seq, uint64_t offset, size_t len) {
    Bytes p(10 + len, 0);
    for (int i = 0; i < 4; i++) p[i] = static_cast<uint8_t>((seq >> (8 * i)) & 0xFF);
    for (int i = 0; i < 6; i++) p[4 + i] = static_cast<uint8_t>((offset >> (8 * i)) & 0xFF);
    for (size_t i = 0; i < len; i++) p[10 + i] = pattern(offset + i);
    return p;
}

static int push(FrameAssembler& fa, const Bytes& p) {
    return fa.push_packet(p.data(), static_cast<int>(p.size()));
}

// expected frame content for stream bytes [start, start + n)
static Bytes stream_bytes(uint64_t start, size_t n) {
    Bytes b(n);
    for (size_t i = 0; i < n; i++) b[i] = pattern(start + i);
    return b;
}

TEST_CASE(in_order_packets_assemble_frames_across_packet_boundaries) {
    FrameAssembler fa;
    fa.configure(100);
    // 40-byte packets: frame 0 completes inside packet 3, frame 1 inside packet 5
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(3, 80, 40)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 100));
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 0);
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 100));

    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.received_packets, 5u);
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.dropped_packet_events, 0u);
    CHECK_EQ(st.adc_data_byte_count, static_cast<uint64_t>(200));
}

TEST_CASE(packet_aligned_to_frame_boundary) {
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 50)), 0);
    CHECK_EQ(push(fa, make_packet(2, 50, 50)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 100));
    CHECK_EQ(push(fa, make_packet(3, 100, 50)), 0);
    CHECK_EQ(push(fa, make_packet(4, 150, 50)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 100));
}

TEST_CASE(packet_larger_than_frame_completes_several_frames) {
    // Documented hazard: push_packet returns 2 but only the LAST completed
    // frame stays available through get_frame_bytes().
    FrameAssembler fa;
    fa.configure(50);
    CHECK_EQ(push(fa, make_packet(1, 0, 120)), 2);
    CHECK(fa.get_frame_bytes() == stream_bytes(50, 50));
    // 20 bytes of the next frame are pending; 30 more complete it
    CHECK_EQ(push(fa, make_packet(2, 120, 30)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 50));
}

TEST_CASE(too_short_packets_are_ignored) {
    FrameAssembler fa;
    fa.configure(100);
    Bytes p = make_packet(1, 0, 40);
    CHECK_EQ(fa.push_packet(p.data(), 10), 0);  // header only, no payload
    CHECK_EQ(fa.push_packet(p.data(), 0), 0);
    CHECK_EQ(fa.push_packet(p.data(), -5), 0);
    CHECK_EQ(fa.get_stats().received_packets, 0u);
    // the real first packet is still accepted as in-order
    CHECK_EQ(push(fa, p), 0);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 0u);
}

TEST_CASE(dropped_packet_inside_a_frame_is_zero_filled) {
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    // packet 2 (bytes 40..79) lost; packet 3 carries bytes 80..119
    CHECK_EQ(push(fa, make_packet(3, 80, 40)), 1);

    Bytes expected = stream_bytes(0, 40);
    expected.insert(expected.end(), 40, 0);                 // lost packet -> zeros
    Bytes tail = stream_bytes(80, 20);
    expected.insert(expected.end(), tail.begin(), tail.end());
    CHECK(fa.get_frame_bytes() == expected);

    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, 1u);
    CHECK_EQ(st.dropped_packet_events, 1u);
    CHECK_EQ(st.received_packets, 3u);  // counter follows the sequence number

    // stream continues in order and the next frame is intact
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 0);
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 100));
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);
}

TEST_CASE(multiple_dropped_packets_in_one_gap) {
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 20)), 0);
    CHECK_EQ(push(fa, make_packet(5, 80, 20)), 1);   // packets 2,3,4 lost
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, 3u);
    CHECK_EQ(st.dropped_packet_events, 1u);
    Bytes expected = stream_bytes(0, 20);
    expected.insert(expected.end(), 60, 0);
    Bytes tail = stream_bytes(80, 20);
    expected.insert(expected.end(), tail.begin(), tail.end());
    CHECK(fa.get_frame_bytes() == expected);
}

TEST_CASE(dropped_packet_exactly_at_frame_end_and_start) {
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 50)), 0);
    CHECK_EQ(push(fa, make_packet(2, 50, 50)), 1);
    // packet 3 (bytes 100..149) lost: the next frame starts with 50 zero bytes
    CHECK_EQ(push(fa, make_packet(4, 150, 50)), 1);
    Bytes expected(50, 0);
    Bytes tail = stream_bytes(150, 50);
    expected.insert(expected.end(), tail.begin(), tail.end());
    CHECK(fa.get_frame_bytes() == expected);
}

TEST_CASE(byte_count_gap_without_sequence_gap_is_zero_filled) {
    // sequence numbers are in order but the byte counter jumped by 20
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 60, 40)), 1);
    Bytes expected = stream_bytes(0, 40);
    expected.insert(expected.end(), 20, 0);
    Bytes tail = stream_bytes(60, 40);
    expected.insert(expected.end(), tail.begin(), tail.end());
    CHECK(fa.get_frame_bytes() == expected);
    CHECK_EQ(fa.get_stats().dropped_packets, 0u);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 0u);
}

TEST_CASE(sequence_number_wraps_at_uint32) {
    // First packet claims seq 0xFFFFFFFF (counted as a drop event, since
    // numbering should start at 1); seq 0 afterwards is the in-order wrap.
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(0xFFFFFFFFu, 0, 10)), 0);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);
    CHECK_EQ(push(fa, make_packet(0, 10, 10)), 0);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);   // wrap is not a new drop
    CHECK_EQ(fa.get_stats().received_packets, 0u);
    CHECK_EQ(push(fa, make_packet(1, 20, 10)), 0);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);
    CHECK_EQ(fa.get_stats().adc_data_byte_count, static_cast<uint64_t>(30));
}

TEST_CASE(byte_count_uses_all_six_header_bytes) {
    // a byte count above 32 bits must be decoded (uint48). Seq 2 on a fresh
    // assembler is a drop, so the whole count is zero-filled, then the payload
    // is counted on top.
    FrameAssembler fa;
    fa.configure(100);
    const uint64_t big = (1ull << 40) + 1000;
    push(fa, make_packet(2, big, 20));
    CHECK_EQ(fa.get_stats().adc_data_byte_count, big + 20);
}

TEST_CASE(byte_count_gap_leaves_counter_behind_and_zero_fills_next_packet) {
    // Bug pinned (FrameAssembler.cpp:96-101): in the byte-count-mismatch
    // branch the payload is copied but never added to adc_data_byte_count_,
    // so the NEXT in-order packet looks like it has a gap and is preceded by
    // spurious zero padding.
    FrameAssembler fa;
    fa.configure(200);
    Bytes first_frame;
    uint64_t offsets[5] = {0, 60, 100, 140, 180};  // 20 bytes lost before packet 2
    for (uint32_t i = 0; i < 5; i++) {
        if (push(fa, make_packet(i + 1, offsets[i], 40)) > 0 && first_frame.empty())
            first_frame = fa.get_frame_bytes();
    }
    Bytes expected = stream_bytes(0, 40);
    expected.insert(expected.end(), 20, 0);
    Bytes rest = stream_bytes(60, 140);
    expected.insert(expected.end(), rest.begin(), rest.end());
    KNOWN_BUG(first_frame == expected,
              "byte-count gap makes the following packet get spurious zero fill");
}

TEST_CASE(out_of_order_packet_corrupts_counters) {
    // Bugs pinned (FrameAssembler.cpp:93-101): a duplicate / reordered packet
    // makes (seq - received - 1) and (byte_count - adc_count) underflow, so
    // dropped_packets jumps by ~4 billion and a spurious frame is emitted.
    FrameAssembler fa;
    fa.configure(100);
    push(fa, make_packet(1, 0, 40));
    push(fa, make_packet(2, 40, 40));
    push(fa, make_packet(3, 80, 40));
    int frames = push(fa, make_packet(2, 40, 40));  // late duplicate of packet 2
    KNOWN_BUG(fa.get_stats().dropped_packets < 1000u,
              "out-of-order packet underflows dropped_packets");
    KNOWN_BUG(frames == 0, "out-of-order packet emits a spurious frame");
}

TEST_CASE(gap_spanning_a_frame_boundary_misaligns_next_frame) {
    // Bug pinned (FrameAssembler.cpp:68-72): when the zero fill crosses the
    // end of the frame, finalize_frame() restarts at index 0 and the
    // overshoot is lost, so every later byte lands too early in its frame.
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    // packet 3 (bytes 80..119) lost: frame 0 ends with 20 zero bytes ...
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 1);
    Bytes frame0 = stream_bytes(0, 80);
    frame0.insert(frame0.end(), 20, 0);
    CHECK(fa.get_frame_bytes() == frame0);                 // ... correct
    // ... and frame 1 should begin with the other 20 lost bytes (zeros)
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 0);
    CHECK_EQ(push(fa, make_packet(6, 200, 40)), 1);
    Bytes frame1(20, 0);
    Bytes rest = stream_bytes(120, 80);
    frame1.insert(frame1.end(), rest.begin(), rest.end());
    KNOWN_BUG(fa.get_frame_bytes() == frame1,
              "zero fill past a frame boundary is not carried into the next frame");
}

TEST_CASE(configure_resets_state_and_stats) {
    FrameAssembler fa;
    fa.configure(100);
    push(fa, make_packet(1, 0, 40));
    push(fa, make_packet(3, 80, 40));
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);
    fa.configure(60);
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.received_packets, 0u);
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.adc_data_byte_count, static_cast<uint64_t>(0));
    CHECK_EQ(fa.get_frame_bytes().size(), static_cast<size_t>(60));
    CHECK_EQ(push(fa, make_packet(1, 0, 60)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 60));
}

TEST_CASE(reset_stats_keeps_frame_assembly_position) {
    // reset_stats() zeroes the counters including received_packets, so the next
    // in-order packet (seq 3) is then counted as a drop event.
    FrameAssembler fa;
    fa.configure(100);
    push(fa, make_packet(1, 0, 40));
    push(fa, make_packet(2, 40, 40));
    fa.reset_stats();
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.received_packets, 0u);
    CHECK_EQ(st.adc_data_byte_count, static_cast<uint64_t>(0));
    // frame assembly position survives: packet 3 still completes frame 0 cleanly
    // only if the byte-count bookkeeping isn't confused by the reset; pin what
    // happens today.
    int frames = push(fa, make_packet(3, 80, 40));
    CHECK_EQ(frames, 1);
    CHECK_EQ(fa.get_stats().dropped_packet_events, 1u);
}

TEST_MAIN()
