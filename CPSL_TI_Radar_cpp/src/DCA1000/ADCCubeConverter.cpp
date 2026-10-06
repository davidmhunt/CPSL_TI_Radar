#include "ADCCubeConverter.hpp"

#include <endian.h>

#include <cstring>

using cpsl::radar::IqOrder;
using cpsl::radar::LvdsLayout;

namespace {

using Cx = std::complex<std::int16_t>;

// little-endian int16 word i of the frame
inline std::int16_t word(const uint8_t* b, size_t i) {
    std::uint16_t u;
    std::memcpy(&u, b + 2 * i, sizeof u);
    return static_cast<std::int16_t>(le16toh(u));
}

// word i, or 0 past the end of a short frame
inline std::int16_t word_or_0(const uint8_t* b, size_t words, size_t i) {
    return i < words ? word(b, i) : std::int16_t(0);
}

}  // namespace

void ADCCubeConverter::configure(size_t num_rx, size_t samples_per_chirp,
                                  size_t chirps_per_frame,
                                  LvdsLayout layout, IqOrder iq_order) {
    num_rx_channels_  = num_rx;
    samples_per_chirp_ = samples_per_chirp;
    chirps_per_frame_  = chirps_per_frame;
    layout_            = layout;
    iq_order_          = iq_order;
}

void ADCCubeConverter::shape(ADCCube& cube) const {
    // resize() to the current size is a no-op, so a correctly shaped buffer
    // is never reallocated
    cube.resize(num_rx_channels_);
    for (auto& rx : cube) {
        rx.resize(samples_per_chirp_);
        for (auto& s : rx) s.resize(chirps_per_frame_);
    }
}

void ADCCubeConverter::convert(const std::vector<uint8_t>& frame_bytes, ADCCube& out)
{
    shape(out);
    switch (layout_) {
        case LvdsLayout::lane_per_rx:
            fill_interleaved(frame_bytes, out);
            break;
        case LvdsLayout::two_lane_iq_pairs:
            fill_noninterleaved(frame_bytes, out);
            break;
    }
}

ADCCubeConverter::ADCCube ADCCubeConverter::convert(
    const std::vector<uint8_t>& frame_bytes)
{
    ADCCube cube;
    convert(frame_bytes, cube);
    return cube;
}

// Both fills loop in OUTPUT order (rx, sample, chirp): the innermost loop
// walks one cube[rx][sample] vector over its chirps, so every write is
// sequential and only the reads stride through the packed frame (core-09
// review F1: about 0.15 ns/byte, within about 2% of a flat layout end to end).
// One pass over the bytes, no intermediate buffer, no allocation.

// lane_per_rx (IWR1443, SDK 2): interleaved format. Per time step
// t = chirp * samples + sample the frame holds 2 * rx words: one component
// for rx 0..N-1, then the other (the first group is real when i_first, the
// v1 behaviour).
void ADCCubeConverter::fill_interleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube)
{
    const size_t R = num_rx_channels_, S = samples_per_chirp_, C = chirps_per_frame_;
    const uint8_t* b = frame_bytes.data();
    const size_t words = frame_bytes.size() / 2;
    const size_t re_off = iq_order_ == IqOrder::i_first ? 0 : R;
    const size_t im_off = iq_order_ == IqOrder::i_first ? R : 0;
    const size_t step = 2 * R;          // words per time step
    const size_t chirp_step = S * step;  // words per chirp
    const bool whole = words >= C * chirp_step;

    for (size_t r = 0; r < R; r++) {
        for (size_t s = 0; s < S; s++) {
            Cx* row = cube[r][s].data();
            size_t w = s * step + r;
            if (whole) {
                for (size_t c = 0; c < C; c++, w += chirp_step) {
                    row[c] = Cx(word(b, w + re_off), word(b, w + im_off));
                }
            } else {
                for (size_t c = 0; c < C; c++, w += chirp_step) {
                    row[c] = Cx(word_or_0(b, words, w + re_off), word_or_0(b, words, w + im_off));
                }
            }
        }
    }
}

// two_lane_iq_pairs (IWR1843 / IWR6843, SDK 3+): non-interleaved format,
// samples in (chirp, rx, sample) order, n = (chirp * rx_count + rx) *
// samples + sample. Every group of four words [A0, A1, B0, B1] holds samples
// 2g and 2g+1: sample 2g+k is (A_k, B_k). q_first (the v1 behaviour): A is
// imag, B real; i_first: A real, B imag.
void ADCCubeConverter::fill_noninterleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube)
{
    const size_t R = num_rx_channels_, S = samples_per_chirp_, C = chirps_per_frame_;
    const uint8_t* b = frame_bytes.data();
    const size_t words = frame_bytes.size() / 2;
    const bool q_first = iq_order_ == IqOrder::q_first;
    const size_t per_chirp = R * S;  // samples per chirp
    // a complete group of four words for every sample
    const bool whole = words >= 4 * ((per_chirp * C + 1) / 2);

    for (size_t r = 0; r < R; r++) {
        for (size_t s = 0; s < S; s++) {
            Cx* row = cube[r][s].data();
            size_t n = r * S + s;  // sample index in chirp 0
            if (whole && per_chirp % 2 == 0) {
                // the usual case: n keeps its parity, so A/B are a fixed
                // stride (two words per sample) apart from chirp to chirp
                size_t w = 4 * (n >> 1) + (n & 1);
                const size_t stride = 2 * per_chirp;
                if (q_first) {
                    for (size_t c = 0; c < C; c++, w += stride) row[c] = Cx(word(b, w + 2), word(b, w));
                } else {
                    for (size_t c = 0; c < C; c++, w += stride) row[c] = Cx(word(b, w), word(b, w + 2));
                }
            } else {
                for (size_t c = 0; c < C; c++, n += per_chirp) {
                    const size_t w = 4 * (n >> 1) + (n & 1);
                    const std::int16_t a = word_or_0(b, words, w), bb = word_or_0(b, words, w + 2);
                    row[c] = q_first ? Cx(bb, a) : Cx(a, bb);
                }
            }
        }
    }
}
