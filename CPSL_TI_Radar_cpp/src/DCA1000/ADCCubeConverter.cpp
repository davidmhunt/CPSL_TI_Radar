#include "ADCCubeConverter.hpp"
#include <endian.h>
#include <iostream>

using cpsl::radar::IqOrder;
using cpsl::radar::LvdsLayout;

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

std::vector<std::int16_t> ADCCubeConverter::convert_from_bytes_to_ints(
    const std::vector<uint8_t>& in_vector)
{
    std::vector<std::int16_t> out_vector(in_vector.size() / 2, 0);
    for (size_t i = 0; i < in_vector.size() / 2; i++) {
        out_vector[i] = static_cast<std::int16_t>(
            (in_vector[i * 2]) | (in_vector[i * 2 + 1] << 8));
        out_vector[i] = le16toh(out_vector[i]);
    }
    return out_vector;
}

// Fills rows first: out[row][col] = in_vector[row + col*num_rows]
std::vector<std::vector<std::int16_t>> ADCCubeConverter::reshape_to_2D(
    std::vector<std::int16_t>& in_vector, size_t num_rows)
{
    std::vector<std::vector<std::int16_t>> out_vector(
        num_rows, std::vector<std::int16_t>(in_vector.size() / num_rows, 0));

    size_t in_idx = 0, row = 0, col = 0;
    while (in_idx < in_vector.size()) {
        out_vector[row][col] = in_vector[in_idx];
        if (++row >= num_rows) { row = 0; ++col; }
        ++in_idx;
    }
    return out_vector;
}

// Pairs each group of four int16 words [A0, A1, B0, B1] (two samples) into
// complex values. q_first (the v1 behaviour): A = imag, B = real. i_first:
// A = real, B = imag.
std::vector<std::complex<std::int16_t>> ADCCubeConverter::interleave_data(
    std::vector<std::vector<std::int16_t>>& in_vector)
{
    std::vector<std::complex<std::int16_t>> out_vector(
        samples_per_chirp_ * chirps_per_frame_ * num_rx_channels_,
        std::complex<std::int16_t>(0, 0));

    const bool q_first = iq_order_ == IqOrder::q_first;
    for (size_t i = 0; i < in_vector[0].size(); i++) {
        size_t idx = i * 2;
        const std::int16_t a0 = in_vector[0][i], a1 = in_vector[1][i];
        const std::int16_t b0 = in_vector[2][i], b1 = in_vector[3][i];
        out_vector[idx]     = q_first ? std::complex<std::int16_t>(b0, a0) : std::complex<std::int16_t>(a0, b0);
        out_vector[idx + 1] = q_first ? std::complex<std::int16_t>(b1, a1) : std::complex<std::int16_t>(a1, b1);
    }
    return out_vector;
}

// lane_per_rx (IWR1443, SDK 2): interleaved format; the two components are
// stored in separate Rx-grouped rows (first group real when i_first, the v1 behaviour)
void ADCCubeConverter::fill_interleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube_)
{
    std::vector<std::int16_t> adc_ints = convert_from_bytes_to_ints(frame_bytes);
    std::vector<std::vector<std::int16_t>> reshaped = reshape_to_2D(
        adc_ints, num_rx_channels_ * 2);

    const size_t re_off = iq_order_ == IqOrder::i_first ? 0 : num_rx_channels_;
    const size_t im_off = iq_order_ == IqOrder::i_first ? num_rx_channels_ : 0;
    for (size_t chirp = 0; chirp < chirps_per_frame_; chirp++) {
        for (size_t sample = 0; sample < samples_per_chirp_; sample++) {
            size_t idx = chirp * samples_per_chirp_ + sample;
            for (size_t rx = 0; rx < num_rx_channels_; rx++) {
                cube_[rx][sample][chirp].real(reshaped[rx + re_off][idx]);
                cube_[rx][sample][chirp].imag(reshaped[rx + im_off][idx]);
            }
        }
    }
}

// two_lane_iq_pairs (IWR1843 / IWR6843, SDK 3+): non-interleaved format, I/Q pairs on 2 lanes
void ADCCubeConverter::fill_noninterleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube_)
{
    std::vector<std::int16_t> adc_ints = convert_from_bytes_to_ints(frame_bytes);
    std::vector<std::vector<std::int16_t>> reshaped = reshape_to_2D(adc_ints, 4);
    std::vector<std::complex<std::int16_t>> interleaved = interleave_data(reshaped);

    size_t idx = 0;
    for (size_t chirp = 0; chirp < chirps_per_frame_; chirp++) {
        for (size_t rx = 0; rx < num_rx_channels_; rx++) {
            for (size_t sample = 0; sample < samples_per_chirp_; sample++) {
                cube_[rx][sample][chirp] = interleaved[idx++];
            }
        }
    }
}
