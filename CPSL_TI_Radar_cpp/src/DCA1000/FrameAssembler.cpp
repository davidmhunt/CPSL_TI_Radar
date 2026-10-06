#include "FrameAssembler.hpp"

#include <algorithm>
#include <cstring>

namespace {

void add_sat(uint32_t& counter, uint64_t n) {
    const uint64_t sum = static_cast<uint64_t>(counter) + n;
    counter = sum > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(sum);
}

}  // namespace

constexpr size_t FrameAssembler::kDefaultReorderSlackPackets;
constexpr size_t FrameAssembler::kResyncPackets;
constexpr size_t FrameAssembler::kResyncWindowFrames;

void FrameAssembler::configure(size_t bytes_per_frame, size_t reorder_slack_bytes) {
    bytes_per_frame_ = bytes_per_frame;
    // two open frames at most: the slack must end inside the next frame
    slack_ = bytes_per_frame == 0 ? 0 : std::min(reorder_slack_bytes, bytes_per_frame - 1);
    for (Slot& s : slots_) {
        s.bytes.assign(bytes_per_frame, 0);
        s.have.clear();
        s.have.reserve(8);
    }
    completed_frame_.assign(bytes_per_frame, 0);
    completed_index_ = 0;
    started_         = false;
    base_            = 0;
    front_           = 0;
    have_seq_        = false;
    newest_seq_      = 0;
    seq_window_      = 0;
    gap_n_           = 0;
    index_bias_      = 0;
    rebase_pending_  = false;
    next_index_      = 0;
    for (std::vector<Held>* v : {&run_, &replay_}) {
        v->assign(kResyncPackets, Held());
        for (Held& h : *v) h.bytes.reserve(1472);  // a DCA1000 packet: no allocation on a resync
    }
    run_n_       = 0;
    run_end_     = 0;
    max_payload_ = 0;
    stats_       = Stats();
}

void FrameAssembler::set_frame_sink(FrameSink sink) { sink_ = std::move(sink); }

void FrameAssembler::reset_stats() {
    stats_ = Stats();
    run_n_ = 0;  // its packets were counted in the old stats
    gap_n_ = 0;
    // the next sequence number is compared against 0, as if seq 0 had just arrived
    have_seq_   = true;
    newest_seq_ = 0;
    seq_window_ = 1;
}

FrameAssembler::Stats FrameAssembler::get_stats() const { return stats_; }

const std::vector<uint8_t>& FrameAssembler::get_frame_bytes() const { return completed_frame_; }

uint64_t FrameAssembler::get_frame_index() const { return completed_index_; }

uint32_t FrameAssembler::parse_sequence_number(const uint8_t* data) {
    return (static_cast<uint32_t>(data[3]) << 24) | (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[1]) << 8) | static_cast<uint32_t>(data[0]);
}

uint64_t FrameAssembler::parse_byte_count(const uint8_t* data) {
    return (static_cast<uint64_t>(data[9]) << 40) | (static_cast<uint64_t>(data[8]) << 32) |
           (static_cast<uint64_t>(data[7]) << 24) | (static_cast<uint64_t>(data[6]) << 16) |
           (static_cast<uint64_t>(data[5]) << 8) | static_cast<uint64_t>(data[4]);
}

void FrameAssembler::open_gap(uint32_t first, uint32_t last) {
    stats_.dropped_packet_events += 1;
    // gaps that fell out of the 64-packet window can no longer be filled
    size_t keep = 0;
    for (size_t i = 0; i < gap_n_; i++) {
        if (newest_seq_ - gaps_[i].last < 64) gaps_[keep++] = gaps_[i];
    }
    gap_n_ = keep;
    if (gap_n_ == kMaxGaps) {  // cannot happen inside 64 packets; keep the newest
        std::memmove(&gaps_[0], &gaps_[1], (kMaxGaps - 1) * sizeof(Gap));
        gap_n_--;
    }
    gaps_[gap_n_++] = Gap{first, last, last - first + 1};
}

void FrameAssembler::fill_gap(uint32_t seq) {
    for (size_t i = 0; i < gap_n_; i++) {
        Gap& g = gaps_[i];
        if (seq - g.first <= g.last - g.first) {  // modulo 2^32
            if (--g.missing == 0) {
                // every packet of this gap arrived late: a reorder, not a drop
                if (stats_.dropped_packet_events > 0) stats_.dropped_packet_events -= 1;
                gaps_[i] = gaps_[--gap_n_];
            }
            return;
        }
    }
}

FrameAssembler::SeqKind FrameAssembler::track_sequence(uint32_t seq) {
    if (!have_seq_) {
        // the DCA1000 numbers packets from 1 after recordStart
        have_seq_   = true;
        newest_seq_ = seq;
        seq_window_ = 1;
        gap_n_      = 0;
        if (seq != 1) {
            if (seq > 1 && seq < 0x80000000u) {
                add_sat(stats_.dropped_packets, seq - 1);
                open_gap(1, seq - 1);
            } else {
                stats_.dropped_packet_events += 1;
            }
        }
        stats_.received_packets = seq;
        return SeqKind::in_order;
    }

    const uint32_t ahead = seq - newest_seq_;  // modulo 2^32: the counter may wrap
    if (ahead != 0 && ahead < 0x80000000u) {
        const uint32_t before   = newest_seq_;
        seq_window_             = ahead >= 64 ? 1 : (seq_window_ << ahead) | 1;
        newest_seq_             = seq;
        stats_.received_packets = seq;
        if (ahead > 1) {
            add_sat(stats_.dropped_packets, ahead - 1);
            open_gap(before + 1, seq - 1);
        }
        return SeqKind::in_order;
    }

    const uint32_t age = newest_seq_ - seq;
    if (age < 64) {
        const uint64_t bit = uint64_t(1) << age;
        if (seq_window_ & bit) {
            stats_.duplicate_packets += 1;
            return SeqKind::duplicate;
        }
        seq_window_ |= bit;
        if (stats_.dropped_packets > 0) stats_.dropped_packets -= 1;  // it filled a gap
        fill_gap(seq);
    }
    stats_.late_packets += 1;
    return SeqKind::late;
}

void FrameAssembler::add_range(Slot& s, size_t begin, size_t end) {
    std::vector<std::pair<size_t, size_t>>& h = s.have;
    if (h.empty() || begin > h.back().second) {  // the usual case: a new run after the last
        h.emplace_back(begin, end);
        return;
    }
    if (begin >= h.back().first) {  // extends (or repeats) the last run
        h.back().second = std::max(h.back().second, end);
        return;
    }
    size_t i = 0;
    while (i < h.size() && h[i].second < begin) i++;
    size_t j  = i;
    size_t lo = begin, hi = end;
    while (j < h.size() && h[j].first <= end) {
        lo = std::min(lo, h[j].first);
        hi = std::max(hi, h[j].second);
        j++;
    }
    h.erase(h.begin() + static_cast<std::ptrdiff_t>(i), h.begin() + static_cast<std::ptrdiff_t>(j));
    h.insert(h.begin() + static_cast<std::ptrdiff_t>(i), std::make_pair(lo, hi));
}

bool FrameAssembler::complete(const Slot& s) const {
    return s.have.size() == 1 && s.have[0].first == 0 && s.have[0].second == bytes_per_frame_;
}

int FrameAssembler::close_base() {
    Slot& s = slot(base_);
    int emitted = 0;
    if (s.have.empty()) {
        add_sat(stats_.skipped_frames, 1);
    } else {
        // zero what never arrived (the buffer holds an older frame's bytes)
        size_t missing = 0, at = 0;
        for (const std::pair<size_t, size_t>& r : s.have) {
            if (r.first > at) {
                std::memset(&s.bytes[at], 0, r.first - at);
                missing += r.first - at;
            }
            at = r.second;
        }
        if (at < bytes_per_frame_) {
            std::memset(&s.bytes[at], 0, bytes_per_frame_ - at);
            missing += bytes_per_frame_ - at;
        }
        if (missing > 0) stats_.incomplete_frames += 1;

        completed_frame_.swap(s.bytes);
        completed_index_ = base_ + index_bias_;
        s.have.clear();
        if (sink_) sink_(completed_frame_, completed_index_, missing);
        emitted = 1;
    }
    base_ += 1;
    return emitted;
}

int FrameAssembler::push_packet(const uint8_t* data, int len) {
    if (bytes_per_frame_ == 0) return -1;  // not configured
    if (len <= 10) return 0;

    const uint32_t seq   = parse_sequence_number(data);
    const uint64_t first = parse_byte_count(data);
    const uint64_t end   = first + static_cast<uint64_t>(len - 10);
    const uint64_t B     = bytes_per_frame_;
    const uint64_t W     = kResyncWindowFrames * B;

    // plausibility, before the sequence number is tracked (see the header)
    bool ahead = false, behind = false;
    if (started_) {
        uint64_t allowance = W;
        const uint32_t d = seq - newest_seq_;  // sequence numbers the stream moved
        if (have_seq_ && d != 0 && d < 0x80000000u)
            allowance += static_cast<uint64_t>(d) * std::max<uint64_t>(max_payload_, static_cast<uint64_t>(len - 10));
        ahead  = first > front_ && first - front_ > allowance;
        behind = end + W <= base_ * B;
    }

    const SeqKind kind = track_sequence(seq);
    if (kind == SeqKind::duplicate) return 0;  // its bytes were already handled

    if (ahead || behind) {
        // late as the placement below would count it; ahead: payload discarded
        if (behind && kind == SeqKind::in_order) stats_.late_packets += 1;
        if (ahead) add_sat(stats_.implausible_packets, 1);
        return hold(data, len, first, end, behind || kind == SeqKind::late, ahead);
    }
    run_n_       = 0;  // a plausible packet ends any run
    max_payload_ = std::max<uint64_t>(max_payload_, static_cast<uint64_t>(len - 10));
    return place(data + 10, first, end, kind);
}

int FrameAssembler::place(const uint8_t* payload, uint64_t first, uint64_t end, SeqKind kind) {
    const uint64_t B = bytes_per_frame_;
    int emitted    = 0;
    bool late_data = false;
    for (uint64_t o = first; o < end;) {
        const uint64_t f   = o / B;
        const size_t pos   = static_cast<size_t>(o % B);
        const size_t take  = static_cast<size_t>(std::min<uint64_t>(B - pos, end - o));
        if (!started_) {
            started_ = true;
            base_    = f;
            if (rebase_pending_) {  // after a resync: indices continue past the dropped frames
                index_bias_     = next_index_ - f;
                rebase_pending_ = false;
            }
        }

        if (f < base_) {
            late_data = true;  // its frame was already emitted
        } else {
            // keep f within the two open frames
            while (f >= base_ + 2) {
                emitted += close_base();
                if (f >= base_ + 2 && slot(base_).have.empty() && slot(base_ + 1).have.empty()) {
                    add_sat(stats_.skipped_frames, f - 1 - base_);  // frames base_ .. f-2 got nothing
                    base_ = f - 1;
                }
            }
            Slot& s = slot(f);
            std::memcpy(&s.bytes[pos], payload + (o - first), take);
            add_range(s, pos, pos + take);
            front_                     = std::max(front_, o + take);
            stats_.adc_data_byte_count = std::max(stats_.adc_data_byte_count, o + take);

            // emit the oldest frame once it is whole, or once the stream is slack past its end
            for (;;) {
                if (complete(slot(base_)) || front_ >= (base_ + 1) * B + slack_) {
                    emitted += close_base();
                } else {
                    break;
                }
            }
        }
        o += take;
    }
    if (late_data && kind == SeqKind::in_order) stats_.late_packets += 1;
    return emitted;
}

int FrameAssembler::hold(const uint8_t* data, int len, uint64_t first, uint64_t end, bool late, bool implausible) {
    if (run_n_ > 0 && first != run_end_) run_n_ = 0;  // not contiguous: a new run starts here
    Held& h = run_[run_n_++];
    h.bytes.assign(data, data + len);
    h.counted_late        = late;
    h.counted_implausible = implausible;
    run_end_              = end;
    return run_n_ < kResyncPackets ? 0 : resync();
}

int FrameAssembler::resync() {
    // drop the open frames; the next emitted index follows them
    const uint64_t span = !slot(base_ + 1).have.empty() ? 2 : (!slot(base_).have.empty() ? 1 : 0);
    add_sat(stats_.skipped_frames, span);
    next_index_     = base_ + index_bias_ + span;
    rebase_pending_ = true;
    for (Slot& s : slots_) s.have.clear();
    started_                   = false;
    front_                     = 0;
    stats_.adc_data_byte_count = 0;
    // the run's packets are replayed below and counted again as they land
    for (size_t i = 0; i < run_n_; i++) {
        if (run_[i].counted_late && stats_.late_packets > 0) stats_.late_packets -= 1;
        if (run_[i].counted_implausible && stats_.implausible_packets > 0) stats_.implausible_packets -= 1;
    }
    // sequence tracking restarts just before the run's first packet
    have_seq_   = true;
    newest_seq_ = parse_sequence_number(run_[0].bytes.data()) - 1;
    seq_window_ = ~uint64_t(0);
    gap_n_      = 0;
    add_sat(stats_.resyncs, 1);

    std::swap(run_, replay_);
    const size_t n = run_n_;
    run_n_         = 0;
    int emitted    = 0;
    for (size_t i = 0; i < n; i++) {
        emitted += push_packet(replay_[i].bytes.data(), static_cast<int>(replay_[i].bytes.size()));
    }
    return emitted;
}

int FrameAssembler::flush() {
    run_n_ = 0;
    if (bytes_per_frame_ == 0 || !started_) return 0;
    int emitted = 0;
    while (!slot(base_).have.empty() || !slot(base_ + 1).have.empty()) emitted += close_base();
    return emitted;
}
