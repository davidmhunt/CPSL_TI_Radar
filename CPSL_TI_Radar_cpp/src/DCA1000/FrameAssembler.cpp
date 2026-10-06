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
    stats_           = Stats();
}

void FrameAssembler::set_frame_sink(FrameSink sink) { sink_ = std::move(sink); }

void FrameAssembler::reset_stats() {
    stats_ = Stats();
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

FrameAssembler::SeqKind FrameAssembler::track_sequence(uint32_t seq) {
    if (!have_seq_) {
        // the DCA1000 numbers packets from 1 after recordStart
        have_seq_ = true;
        if (seq != 1) {
            stats_.dropped_packet_events += 1;
            if (seq > 1 && seq < 0x80000000u) add_sat(stats_.dropped_packets, seq - 1);
        }
        newest_seq_             = seq;
        seq_window_             = 1;
        stats_.received_packets = seq;
        return SeqKind::in_order;
    }

    const uint32_t ahead = seq - newest_seq_;  // modulo 2^32: the counter may wrap
    if (ahead != 0 && ahead < 0x80000000u) {
        if (ahead > 1) {
            add_sat(stats_.dropped_packets, ahead - 1);
            stats_.dropped_packet_events += 1;
        }
        seq_window_             = ahead >= 64 ? 1 : (seq_window_ << ahead) | 1;
        newest_seq_             = seq;
        stats_.received_packets = seq;
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
        completed_index_ = base_;
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
    const uint8_t* payload = data + 10;
    const uint64_t B = bytes_per_frame_;

    const SeqKind kind = track_sequence(seq);
    if (kind == SeqKind::duplicate) return 0;  // its bytes were already handled

    int emitted    = 0;
    bool late_data = false;
    for (uint64_t o = first; o < end;) {
        const uint64_t f   = o / B;
        const size_t pos   = static_cast<size_t>(o % B);
        const size_t take  = static_cast<size_t>(std::min<uint64_t>(B - pos, end - o));
        if (!started_) {
            started_ = true;
            base_    = f;
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

int FrameAssembler::flush() {
    if (bytes_per_frame_ == 0 || !started_) return 0;
    int emitted = 0;
    while (!slot(base_).have.empty() || !slot(base_ + 1).have.empty()) emitted += close_base();
    return emitted;
}
