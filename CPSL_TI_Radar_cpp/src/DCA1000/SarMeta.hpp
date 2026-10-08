#ifndef CPSL_RADAR_SAR_META_HPP
#define CPSL_RADAR_SAR_META_HPP

// Per-chirp metadata of the iwr1843_sar_lvds firmware's LVDS dataFmt 2 (lvds stream format adc_sar_meta,
// directive core-24). The wire format is defined in
// firmware_dev/projects/iwr1843_sar_lvds/docs/lvds_data_format.md ("the format doc"); its reference parser is
// firmware_dev/projects/iwr1843_sar_lvds/tools/sar_parse.py, which this decoder matches chirp for chirp
// (tests/test_sar_meta.cpp compares against its output).
//
// Packet k of a recording (chirp k) = optional HSI header (H bytes) + ADC block + two 32-byte record slots, B
// bytes in all, back to back from byte 0 of the recording. Packet k's own record is slot k mod 2; the other
// slot holds a neighbour's record and is never used. A record is valid only if all its bytes arrived, magic is
// "SARM", version 1, globalChirpIdx == k (mod 2^32) and runIdx is the run's (the runIdx of the first record
// that matches magic, version and position). An invalid record is discarded whole (time, saturation); the
// chirp's ADC data is kept.
//
// SarMetaDecoder runs on the DCA worker thread, once per assembled frame (Nc packets); nothing here allocates
// once ChirpMetaFrame::chirps has Nc entries, logs or throws.

#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace cpsl {
namespace radar {

// record flags (format doc section 2)
constexpr uint16_t kSarFlagSatValid = 0x1;  // satSlices / satRefLag hold a result
constexpr uint16_t kSarFlagSatMon = 0x2;    // saturation monitor enabled in this run
constexpr uint16_t kSarFlagLate = 0x4;      // chirp-start interrupt late: the write may have missed packet k
constexpr uint16_t kSarFlagSkip = 0x8;      // chirp-start interrupts missed, counters realigned
constexpr uint16_t kSarFlagResync = 0x10;   // counters wrong at a frame start, reset
constexpr uint32_t kSarMagic = 0x4D524153;  // "SARM"
constexpr double kSarTicksPerSecond = 100e6;  // tsTicks: RTI counter, 10 ns

struct ChirpMeta {
    // k: the packet's position in the recording (frame number * Nc + chirp in frame). Restarts at 0 after a
    // DCA1000 resync (a new recording).
    uint64_t chirp = 0;
    bool record_valid = false;  // slot k mod 2 passed validation (above)
    bool adc_complete = false;  // every byte of the chirp's ADC block arrived (lost bytes are zeros)

    // the record (format doc section 2); all 0 unless record_valid
    uint16_t version = 0;
    uint16_t flags = 0;
    uint32_t frame_idx = 0;
    uint16_t chirp_in_frame = 0;
    uint16_t num_chirps_per_frame = 0;
    uint32_t global_chirp_idx = 0;
    uint16_t run_idx = 0;
    uint8_t sat_slices = 0;   // saturation result of chirp global_chirp_idx - sat_ref_lag (not this chirp)
    uint8_t sat_ref_lag = 0;
    uint64_t ts_ticks = 0;    // chirp start, 10 ns ticks since boot

    // host side
    // seconds since the run's first valid record (sar_parse t_s): the record's time, or (record invalid)
    // interpolated per format doc section 2 from the latest valid record of the run before this chirp, else
    // the first valid one later in this frame. has_time false: no valid record known to interpolate from.
    bool has_time = false;
    bool time_interpolated = false;
    double t_s = 0.0;
    // this chirp's own saturation, aligned by satRefLag (format doc section 3): saturated primary slices, -1 =
    // unknown. Filled from this frame's records; the result for the last one or two chirps of a frame usually
    // arrives in the next frame's records: see ChirpMetaFrame::prev_tail_sat.
    int16_t sat_slices_aligned = -1;
};

// The metadata of one adc_sar_meta frame (AdcFrame::meta). Empty `chirps` for the plain adc format.
struct ChirpMetaFrame {
    std::vector<ChirpMeta> chirps;  // one per chirp of the frame, in order
    // Saturation results this frame's records carried for the previous frame's last two chirps: [1] = its
    // last chirp, [0] = the one before; -1 = none. They complete that frame's sat_slices_aligned (a result can
    // arrive twice with the same value, or never).
    int16_t prev_tail_sat[2] = {-1, -1};
    bool run_known = false;  // a record has fixed the run (runIdx below)
    uint16_t run_idx = 0;
    uint32_t records_valid = 0;      // chirps of this frame with a valid record
    uint32_t records_invalid = 0;    // chirps of this frame without one (failed, or record bytes lost)
    uint32_t records_other_run = 0;  // records with magic SARM but another runIdx (a second run in the recording)
};

class SarMetaDecoder {
public:
    // Nc chirps per frame, packet bytes B, header bytes H, ADC block end M (= H + 4 * rx * samples), chirp cycle
    // Tc and frame blank Tb in seconds (RadarConfigReader::get_chirp_cycle_s / get_frame_blank_s). Resets the run.
    void configure(size_t chirps_per_frame, size_t packet_bytes, size_t header_bytes, size_t adc_end, double tc_s,
                   double tb_s);
    // Forget the run (runIdx, time origin, last valid record): the next frame starts a new recording (a
    // FrameAssembler resync).
    void reset_run();

    // Decode frame `frame_number` (stream offset / frame bytes) of the current recording. `received` = the
    // byte ranges that arrived (FrameAssembler::get_frame_received); `complete` = no byte missing (then
    // `received` is not consulted). `out.chirps` is resized to Nc (no allocation once it has that size).
    void decode(const uint8_t* frame, size_t len, uint64_t frame_number,
                const std::vector<std::pair<size_t, size_t>>& received, bool complete, ChirpMetaFrame& out);

private:
    size_t nc_ = 0, b_ = 0, h_ = 0, m_ = 0;
    double tc_s_ = 0.0, tb_s_ = 0.0;
    bool run_known_ = false;
    uint16_t run_idx_ = 0;
    bool has_t0_ = false;
    uint64_t t0_ticks_ = 0;
    bool has_last_ = false;  // latest valid record of the run: chirp and time (seconds since t0)
    uint64_t last_k_ = 0;
    double last_t_s_ = 0.0;
};

}  // namespace radar
}  // namespace cpsl

#endif
