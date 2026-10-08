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
    packet_bytes_      = 0;
    header_bytes_      = 0;
}

void ADCCubeConverter::configure_packets(size_t packet_bytes, size_t header_bytes) {
    packet_bytes_ = packet_bytes;
    header_bytes_ = header_bytes;
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
    if (packet_bytes_ != 0) {  // adc_sar_meta (core-24): its own loop, the packed paths below are untouched
        fill_packets(frame_bytes, out);
        return;
    }
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

void ADCCubeConverter::file_order(const std::vector<uint8_t>& frame_bytes, std::vector<std::int16_t>& out) const
{
    if (packet_bytes_ != 0) {
        file_order_packets(frame_bytes, out);
    } else {
        file_order_packed(frame_bytes, out);
    }
}

void ADCCubeConverter::file_order_packed(const std::vector<uint8_t>& frame_bytes, std::vector<std::int16_t>& out) const
{
    const size_t R = num_rx_channels_, S = samples_per_chirp_, C = chirps_per_frame_;
    const size_t total = R * S * C;  // samples
    out.resize(2 * total);
    const uint8_t* b = frame_bytes.data();
    const size_t words = frame_bytes.size() / 2;
    std::int16_t* o = out.data();
    switch (layout_) {
        case LvdsLayout::two_lane_iq_pairs: {
            // the file order is the wire's sample order n; only the four words
            // of each pair are rearranged: [A0 A1 B0 B1] -> (re, im) of 2g, 2g+1
            const bool q_first = iq_order_ == IqOrder::q_first;
            const size_t groups = total / 2;
            if (words >= 4 * groups) {
                for (size_t g = 0; g < groups; g++, o += 4) {
                    const std::int16_t a0 = word(b, 4 * g), a1 = word(b, 4 * g + 1);
                    const std::int16_t b0 = word(b, 4 * g + 2), b1 = word(b, 4 * g + 3);
                    if (q_first) {
                        o[0] = b0; o[1] = a0; o[2] = b1; o[3] = a1;
                    } else {
                        o[0] = a0; o[1] = b0; o[2] = a1; o[3] = b1;
                    }
                }
                if (total % 2 != 0) {  // an unpaired last sample (as convert())
                    const size_t w = 4 * groups;
                    const std::int16_t a = word_or_0(b, words, w), bb = word_or_0(b, words, w + 2);
                    o[0] = q_first ? bb : a;
                    o[1] = q_first ? a : bb;
                }
            } else {
                for (size_t n = 0; n < total; n++, o += 2) {
                    const size_t w = 4 * (n >> 1) + (n & 1);
                    const std::int16_t a = word_or_0(b, words, w), bb = word_or_0(b, words, w + 2);
                    o[0] = q_first ? bb : a;
                    o[1] = q_first ? a : bb;
                }
            }
            break;
        }
        case LvdsLayout::lane_per_rx: {
            const size_t re_off = iq_order_ == IqOrder::i_first ? 0 : R;
            const size_t im_off = iq_order_ == IqOrder::i_first ? R : 0;
            const size_t step = 2 * R;
            for (size_t c = 0; c < C; c++)
                for (size_t r = 0; r < R; r++)
                    for (size_t s = 0; s < S; s++, o += 2) {
                        const size_t w = (c * S + s) * step + r;
                        o[0] = word_or_0(b, words, w + re_off);
                        o[1] = word_or_0(b, words, w + im_off);
                    }
            break;
        }
    }
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

// adc_sar_meta (core-24): chirp c's samples are packet c's ADC block, n = rx * samples + sample inside it,
// starting at word c * B/2 + H/2. Inside the block the words pair as in fill_noninterleaved: group g = [A0 A1
// B0 B1] holds samples 2g and 2g+1 (rx * samples is even, so no pair straddles a packet). Output order as
// there: sequential writes along cube[rx][sample], reads stride by one packet.
void ADCCubeConverter::fill_packets(const std::vector<uint8_t>& frame_bytes, ADCCube& cube) const
{
    const size_t R = num_rx_channels_, S = samples_per_chirp_, C = chirps_per_frame_;
    const uint8_t* b = frame_bytes.data();
    const size_t words = frame_bytes.size() / 2;
    const bool q_first = iq_order_ == IqOrder::q_first;
    const size_t stride = packet_bytes_ / 2;  // words per chirp packet
    const size_t base = header_bytes_ / 2;
    const bool whole = words >= C * stride;

    for (size_t r = 0; r < R; r++) {
        for (size_t s = 0; s < S; s++) {
            Cx* row = cube[r][s].data();
            const size_t n = r * S + s;
            size_t w = base + 4 * (n >> 1) + (n & 1);
            if (whole) {
                if (q_first) {
                    for (size_t c = 0; c < C; c++, w += stride) row[c] = Cx(word(b, w + 2), word(b, w));
                } else {
                    for (size_t c = 0; c < C; c++, w += stride) row[c] = Cx(word(b, w), word(b, w + 2));
                }
            } else {
                for (size_t c = 0; c < C; c++, w += stride) {
                    const std::int16_t a = word_or_0(b, words, w), bb = word_or_0(b, words, w + 2);
                    row[c] = q_first ? Cx(bb, a) : Cx(a, bb);
                }
            }
        }
    }
}

// adc_data.bin order (for chirp, for rx, for sample: re, im) of an adc_sar_meta frame: each packet's ADC block
// in wire order, header and record slots dropped. Equal to sar_parse.py's _adc.bin when lvds.iq_order matches
// the cfg's SampleSwap (cross_check_radar_cfg).
void ADCCubeConverter::file_order_packets(const std::vector<uint8_t>& frame_bytes, std::vector<std::int16_t>& out) const
{
    const size_t R = num_rx_channels_, S = samples_per_chirp_, C = chirps_per_frame_;
    const size_t per_chirp = R * S;
    out.resize(2 * per_chirp * C);
    const uint8_t* b = frame_bytes.data();
    const size_t words = frame_bytes.size() / 2;
    const bool q_first = iq_order_ == IqOrder::q_first;
    const size_t stride = packet_bytes_ / 2;
    std::int16_t* o = out.data();
    const bool whole = words >= C * stride;
    for (size_t c = 0; c < C; c++) {
        const size_t w0 = c * stride + header_bytes_ / 2;
        for (size_t n = 0; n < per_chirp; n++, o += 2) {
            const size_t w = w0 + 4 * (n >> 1) + (n & 1);
            const std::int16_t a = whole ? word(b, w) : word_or_0(b, words, w);
            const std::int16_t bb = whole ? word(b, w + 2) : word_or_0(b, words, w + 2);
            o[0] = q_first ? bb : a;
            o[1] = q_first ? a : bb;
        }
    }
}
