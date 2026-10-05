// FrameAssembler: DCA1000 UDP packet -> frame assembly, drop detection.
//
// Packet = 10-byte header (uint32 LE sequence number, uint48 LE byte count of
// ADC bytes sent BEFORE this packet) + ADC payload. Sequence numbers start at
// 1. The synthetic stream byte at offset `o` is pattern(o), never 0, so
// zero padding is distinguishable from data.
#include "test_harness.hpp"
#include "FrameAssembler.hpp"

#include <algorithm>

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

TEST_CASE(byte_count_gap_does_not_zero_fill_the_next_packet) {
    // core-02 KNOWN_BUG, fixed by byte-offset placement (P1): a byte-count gap
    // used to leave the counter behind so the next in-order packet got
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
    CHECK(first_frame == expected);
    CHECK_EQ(fa.get_stats().incomplete_frames, 1u);
}

TEST_CASE(late_duplicate_is_counted_not_dropped) {
    // core-02 KNOWN_BUG, fixed: a duplicate / reordered packet used to
    // underflow dropped_packets (~4e9) and emit a spurious frame.
    FrameAssembler fa;
    fa.configure(100);
    push(fa, make_packet(1, 0, 40));
    push(fa, make_packet(2, 40, 40));
    push(fa, make_packet(3, 80, 40));
    int frames = push(fa, make_packet(2, 40, 40));  // late duplicate of packet 2
    CHECK_EQ(fa.get_stats().dropped_packets, 0u);
    CHECK_EQ(frames, 0);
    CHECK_EQ(fa.get_stats().duplicate_packets, 1u);
    CHECK_EQ(fa.get_stats().late_packets, 0u);
    CHECK_EQ(fa.get_stats().received_packets, 3u);
}

TEST_CASE(gap_spanning_a_frame_boundary_keeps_next_frame_aligned) {
    // core-02 KNOWN_BUG, fixed: zero fill past a frame boundary used to be
    // lost, so every later byte landed too early in its frame.
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    // packet 3 (bytes 80..119) lost: frame 0 ends with 20 zero bytes ...
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 1);
    Bytes frame0 = stream_bytes(0, 80);
    frame0.insert(frame0.end(), 20, 0);
    CHECK(fa.get_frame_bytes() == frame0);
    // ... and frame 1 begins with the other 20 lost bytes (zeros). Packet 5
    // reaches frame 1's last byte, so it completes the frame.
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 1);
    Bytes frame1(20, 0);
    Bytes rest = stream_bytes(120, 80);
    frame1.insert(frame1.end(), rest.begin(), rest.end());
    CHECK(fa.get_frame_bytes() == frame1);
    CHECK_EQ(fa.get_frame_index(), static_cast<uint64_t>(1));
    CHECK_EQ(push(fa, make_packet(6, 200, 40)), 0);
    CHECK_EQ(fa.get_stats().incomplete_frames, 2u);
}

TEST_CASE(push_before_configure_is_an_error) {
    FrameAssembler fa;
    Bytes p = make_packet(1, 0, 40);
    CHECK_EQ(push(fa, p), -1);
    CHECK_EQ(fa.flush(), 0);
    CHECK_EQ(fa.get_stats().received_packets, 0u);
    fa.configure(100);
    CHECK_EQ(push(fa, p), 0);
}

TEST_CASE(duplicate_inside_an_open_frame_changes_nothing) {
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(3, 80, 20)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 100));
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.duplicate_packets, 2u);
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.dropped_packet_events, 0u);
    CHECK_EQ(st.incomplete_frames, 0u);
}

TEST_CASE(reorder_inside_a_frame_is_recovered) {
    // packet 3 arrives before packet 2: counted as a drop, then the late
    // packet fills the gap and the drop is taken back
    FrameAssembler fa;
    fa.configure(120);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(3, 80, 20)), 0);
    CHECK_EQ(fa.get_stats().dropped_packets, 1u);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(4, 100, 20)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 120));
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.dropped_packet_events, 1u);
    CHECK_EQ(st.late_packets, 1u);
    CHECK_EQ(st.incomplete_frames, 0u);
}

TEST_CASE(reorder_across_a_frame_boundary_with_slack_is_recovered) {
    // frame 0's last packet arrives after frame 1's first: with reorder
    // slack, frame 0 is held open and completes when the late packet lands
    FrameAssembler fa;
    fa.configure(100, 70);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 0);   // stream end 160 < 100 + 70: held
    CHECK_EQ(push(fa, make_packet(3, 80, 40)), 1);    // late, completes frame 0
    CHECK(fa.get_frame_bytes() == stream_bytes(0, 100));
    CHECK_EQ(fa.get_frame_index(), static_cast<uint64_t>(0));
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 100));
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.late_packets, 1u);
    CHECK_EQ(st.incomplete_frames, 0u);
}

TEST_CASE(reorder_across_a_frame_boundary_without_slack_is_late) {
    // slack 0: frame 0 is emitted as soon as frame 1 data arrives, so its
    // last packet is late; it is counted and dropped, frame 1 stays aligned
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 40)), 0);
    CHECK_EQ(push(fa, make_packet(2, 40, 40)), 0);
    CHECK_EQ(push(fa, make_packet(4, 120, 40)), 1);
    Bytes frame0 = stream_bytes(0, 80);
    frame0.insert(frame0.end(), 20, 0);
    CHECK(fa.get_frame_bytes() == frame0);
    CHECK_EQ(push(fa, make_packet(3, 80, 40)), 0);    // late: [80,100) dropped, [100,120) kept
    CHECK_EQ(push(fa, make_packet(5, 160, 40)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(100, 100));
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, 0u);
    CHECK_EQ(st.late_packets, 1u);
    CHECK_EQ(st.incomplete_frames, 1u);
}

TEST_CASE(gap_longer_than_a_frame_skips_whole_frames) {
    // packets for frames 1..3 lost: frame 0 is emitted with its tail zeroed,
    // frames 1..3 are skipped (never emitted), frame 4 lands at offset 0
    FrameAssembler fa;
    fa.configure(100);
    CHECK_EQ(push(fa, make_packet(1, 0, 50)), 0);
    CHECK_EQ(push(fa, make_packet(10, 400, 50)), 1);
    Bytes frame0 = stream_bytes(0, 50);
    frame0.insert(frame0.end(), 50, 0);
    CHECK(fa.get_frame_bytes() == frame0);
    CHECK_EQ(push(fa, make_packet(11, 450, 50)), 1);
    CHECK(fa.get_frame_bytes() == stream_bytes(400, 100));
    CHECK_EQ(fa.get_frame_index(), static_cast<uint64_t>(4));
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.skipped_frames, 3u);
    CHECK_EQ(st.dropped_packets, 8u);
    CHECK_EQ(st.dropped_packet_events, 1u);
}

TEST_CASE(huge_byte_count_jump_is_bounded) {
    // a corrupt byte count far ahead must not loop per skipped frame
    FrameAssembler fa;
    fa.configure(100);
    push(fa, make_packet(1, 0, 100));
    CHECK_EQ(push(fa, make_packet(2, (1ull << 47), 100)), 1);
    CHECK_EQ(fa.get_frame_index(), (1ull << 47) / 100);
    CHECK(fa.get_stats().skipped_frames > 1000000u);
}

TEST_CASE(sink_sees_every_frame_once_in_order) {
    // one packet that completes two frames: the sink gets both
    FrameAssembler fa;
    fa.configure(50);
    std::vector<uint64_t> idx;
    std::vector<Bytes> got;
    fa.set_frame_sink([&](const Bytes& f, uint64_t i, size_t missing) {
        idx.push_back(i);
        got.push_back(f);
        CHECK_EQ(missing, static_cast<size_t>(0));
    });
    CHECK_EQ(push(fa, make_packet(1, 0, 120)), 2);
    CHECK_EQ(idx.size(), static_cast<size_t>(2));
    CHECK_EQ(idx[0], static_cast<uint64_t>(0));
    CHECK_EQ(idx[1], static_cast<uint64_t>(1));
    CHECK(got[0] == stream_bytes(0, 50));
    CHECK(got[1] == stream_bytes(50, 50));
}

TEST_CASE(flush_emits_open_frames) {
    FrameAssembler fa;
    fa.configure(100, 50);
    push(fa, make_packet(1, 0, 40));
    push(fa, make_packet(3, 80, 40));   // frame 0 has a hole; held for the slack
    CHECK_EQ(fa.flush(), 2);           // frame 0 (incomplete) and frame 1 (20 bytes)
    Bytes frame1 = stream_bytes(100, 20);
    frame1.insert(frame1.end(), 80, 0);
    CHECK(fa.get_frame_bytes() == frame1);
    CHECK_EQ(fa.flush(), 0);
    CHECK_EQ(fa.get_stats().incomplete_frames, 2u);
}

// Golden replay: a seeded stream with drops, duplicates and adjacent swaps
// (some across frame boundaries). Every frame delivered must equal the
// stream bytes with exactly the dropped packets' bytes zeroed, and every
// frame index must come out once.
TEST_CASE(golden_replay_with_drops_duplicates_and_reordering) {
    const size_t B = 1000, P = 97, frames = 40;
    const uint64_t total = B * frames;
    struct Pkt { uint32_t seq; uint64_t off; size_t len; };
    std::vector<Pkt> sent;
    std::vector<bool> dropped_byte(total, false);
    uint64_t s = 12345;
    auto rnd = [&]() { s = s * 6364136223846793005ull + 1442695040888963407ull; return (s >> 33) % 1000; };
    uint32_t seq = 1;
    size_t n_drop = 0, n_dup = 0;
    for (uint64_t off = 0; off < total; off += P, seq++) {
        size_t len = static_cast<size_t>(std::min<uint64_t>(P, total - off));
        bool edge = off == 0 || off + len == total;
        if (!edge && rnd() < 20) {  // 2% dropped
            for (size_t k = 0; k < len; k++) dropped_byte[off + k] = true;
            n_drop++;
            continue;
        }
        sent.push_back({seq, off, len});
        if (!edge && rnd() < 20) { sent.push_back({seq, off, len}); n_dup++; }
    }
    size_t n_swap = 0;
    for (size_t i = 1; i + 2 < sent.size(); i++)
        if (rnd() < 30) { std::swap(sent[i], sent[i + 1]); n_swap++; i++; }
    CHECK(n_drop > 0 && n_dup > 0 && n_swap > 0);

    FrameAssembler fa;
    fa.configure(B, 2 * P);  // slack covers an adjacent swap
    std::vector<uint64_t> idx;
    std::vector<Bytes> got;
    fa.set_frame_sink([&](const Bytes& f, uint64_t i, size_t) { idx.push_back(i); got.push_back(f); });
    for (const Pkt& p : sent) push(fa, make_packet(p.seq, p.off, p.len));
    fa.flush();

    CHECK_EQ(idx.size(), frames);
    for (size_t f = 0; f < idx.size() && f < frames; f++) {
        CHECK_EQ(idx[f], static_cast<uint64_t>(f));
        Bytes expected = stream_bytes(f * B, B);
        for (size_t k = 0; k < B; k++)
            if (dropped_byte[f * B + k]) expected[k] = 0;
        CHECK(got[f] == expected);
    }
    FrameAssembler::Stats st = fa.get_stats();
    CHECK_EQ(st.dropped_packets, static_cast<uint32_t>(n_drop));
    CHECK_EQ(st.duplicate_packets, static_cast<uint32_t>(n_dup));
    CHECK_EQ(st.skipped_frames, 0u);
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
