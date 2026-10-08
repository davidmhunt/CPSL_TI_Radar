#include "SarMeta.hpp"

#include <cstring>

namespace cpsl {
namespace radar {

namespace {

// true if [begin, end) lies inside one received range (the ranges are sorted, disjoint and merged)
bool covered(const std::vector<std::pair<size_t, size_t>>& received, size_t begin, size_t end) {
    for (const std::pair<size_t, size_t>& r : received) {
        if (r.second <= begin) continue;
        return r.first <= begin && end <= r.second;
    }
    return false;
}

inline uint16_t le16(const uint8_t* p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }
inline uint32_t le32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) | (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}
inline uint64_t le64(const uint8_t* p) { return static_cast<uint64_t>(le32(p)) | (static_cast<uint64_t>(le32(p + 4)) << 32); }

}  // namespace

void SarMetaDecoder::configure(size_t chirps_per_frame, size_t packet_bytes, size_t header_bytes, size_t adc_end,
                               double tc_s, double tb_s) {
    nc_ = chirps_per_frame;
    b_ = packet_bytes;
    h_ = header_bytes;
    m_ = adc_end;
    tc_s_ = tc_s;
    tb_s_ = tb_s;
    reset_run();
}

void SarMetaDecoder::reset_run() {
    run_known_ = false;
    run_idx_ = 0;
    has_t0_ = false;
    t0_ticks_ = 0;
    has_last_ = false;
    last_k_ = 0;
    last_t_s_ = 0.0;
}

void SarMetaDecoder::decode(const uint8_t* frame, size_t len, uint64_t frame_number,
                            const std::vector<std::pair<size_t, size_t>>& received, bool complete,
                            ChirpMetaFrame& out) {
    out.chirps.resize(nc_);
    out.prev_tail_sat[0] = out.prev_tail_sat[1] = -1;
    out.records_valid = out.records_invalid = out.records_other_run = 0;
    const uint64_t start = frame_number * nc_;
    const auto interpolate = [this](uint64_t k, uint64_t j, double tj) {
        // format doc section 2, written as sar_parse.py does: tj + (k - j) * Tc + (k // Nc - j // Nc) * Tb
        return tj + static_cast<double>(static_cast<int64_t>(k) - static_cast<int64_t>(j)) * tc_s_ +
               static_cast<double>(static_cast<int64_t>(k / nc_) - static_cast<int64_t>(j / nc_)) * tb_s_;
    };
    bool pending = false;  // chirps before the run's first valid record, waiting for one later in this frame

    for (size_t c = 0; c < nc_; c++) {
        ChirpMeta& m = out.chirps[c];
        m = ChirpMeta();
        const uint64_t k = start + c;
        m.chirp = k;
        const size_t pkt = c * b_;
        m.adc_complete = pkt + m_ <= len && (complete || covered(received, pkt + h_, pkt + m_));
        const size_t rec = pkt + m_ + 32 * static_cast<size_t>(k & 1);
        const bool present = rec + 32 <= len && (complete || covered(received, rec, rec + 32));
        bool valid = false;
        if (present) {
            // step 1 of the byte order: swap bytes 2-3 with 4-5 in each 8-byte group (rec is a multiple of 8)
            uint8_t r[32];
            std::memcpy(r, frame + rec, 32);
            for (size_t g = 0; g < 32; g += 8) {
                std::swap(r[g + 2], r[g + 4]);
                std::swap(r[g + 3], r[g + 5]);
            }
            const uint32_t magic = le32(r);
            const uint16_t version = le16(r + 4);
            const uint32_t gidx = le32(r + 16);
            const uint16_t run = le16(r + 20);
            const bool placed = magic == kSarMagic && version == 1 && gidx == static_cast<uint32_t>(k);
            if (!run_known_ && placed) {
                run_known_ = true;
                run_idx_ = run;
            }
            if (magic == kSarMagic && run_known_ && run != run_idx_) out.records_other_run += 1;
            valid = placed && run_known_ && run == run_idx_;
            if (valid) {
                m.version = version;
                m.flags = le16(r + 6);
                m.frame_idx = le32(r + 8);
                m.chirp_in_frame = le16(r + 12);
                m.num_chirps_per_frame = le16(r + 14);
                m.global_chirp_idx = gidx;
                m.run_idx = run;
                m.sat_slices = r[22];
                m.sat_ref_lag = r[23];
                m.ts_ticks = le64(r + 24);
            }
        }
        m.record_valid = valid;
        if (valid) {
            out.records_valid += 1;
            if (!has_t0_) {
                has_t0_ = true;
                t0_ticks_ = m.ts_ticks;
            }
            m.has_time = true;
            m.t_s = static_cast<double>(static_cast<int64_t>(m.ts_ticks - t0_ticks_)) / kSarTicksPerSecond;
            has_last_ = true;
            last_k_ = k;
            last_t_s_ = m.t_s;
            // saturation of chirp k - lag (format doc section 3); later records overwrite earlier ones
            if (m.flags & kSarFlagSatValid) {
                const int64_t target = static_cast<int64_t>(k) - m.sat_ref_lag;
                const int64_t first = static_cast<int64_t>(start);
                if (target >= first && target < first + static_cast<int64_t>(nc_)) {
                    out.chirps[static_cast<size_t>(target - first)].sat_slices_aligned = m.sat_slices;
                } else if (target >= first - 2 && target < first) {
                    out.prev_tail_sat[target - (first - 2)] = m.sat_slices;
                }
            }
        } else {
            out.records_invalid += 1;
            if (has_last_) {
                m.has_time = true;
                m.time_interpolated = true;
                m.t_s = interpolate(k, last_k_, last_t_s_);
            } else {
                pending = true;
            }
        }
    }
    out.run_known = run_known_;
    out.run_idx = run_idx_;

    // chirps before the run's first valid record: from that record, if it is in this frame (sar_parse uses the
    // run's first valid record; a frame without one leaves them without a time)
    if (pending) {
        size_t first_valid = nc_;
        for (size_t c = 0; c < nc_; c++) {
            if (out.chirps[c].record_valid) {
                first_valid = c;
                break;
            }
        }
        if (first_valid < nc_) {
            const ChirpMeta& j = out.chirps[first_valid];
            for (size_t c = 0; c < first_valid; c++) {
                ChirpMeta& m = out.chirps[c];
                m.has_time = true;
                m.time_interpolated = true;
                m.t_s = interpolate(m.chirp, j.chirp, j.t_s);
            }
        }
    }
}

}  // namespace radar
}  // namespace cpsl
