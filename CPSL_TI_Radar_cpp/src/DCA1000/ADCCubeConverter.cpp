#include "ADCCubeConverter.hpp"
#include <endian.h>
#include <iostream>

void ADCCubeConverter::configure(size_t num_rx, size_t samples_per_chirp,
                                  size_t chirps_per_frame,
                                  const std::string& board_type) {
    num_rx_channels_  = num_rx;
    samples_per_chirp_ = samples_per_chirp;
    chirps_per_frame_  = chirps_per_frame;
    board_type_        = board_type;
    cube_ = ADCCube(
        num_rx, std::vector<std::vector<std::complex<std::int16_t>>>(
            samples_per_chirp, std::vector<std::complex<std::int16_t>>(
                chirps_per_frame, std::complex<std::int16_t>(0, 0)
            )
        )
    );
}

ADCCubeConverter::ADCCube ADCCubeConverter::convert(
    const std::vector<uint8_t>& frame_bytes)
{
    if (board_type_ == "IWR1443") {
        fill_interleaved(frame_bytes);
    } else if (board_type_ == "IWR1843" || board_type_ == "IWR6843") {
        fill_noninterleaved(frame_bytes);
    } else {
        std::cerr << "ADCCubeConverter::convert(): unrecognized board_type \""
                  << board_type_ << "\"" << std::endl;
    }
    return cube_;
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

// Interleaves 4 LVDS lanes [I_lane0, I_lane1, Q_lane0, Q_lane1] into complex values.
// Input columns represent non-interleaved pairs: [Rx0-samp0-I, Rx0-samp1-I, Rx0-samp0-Q, Rx0-samp1-Q]
std::vector<std::complex<std::int16_t>> ADCCubeConverter::interleave_data(
    std::vector<std::vector<std::int16_t>>& in_vector)
{
    std::vector<std::complex<std::int16_t>> out_vector(
        samples_per_chirp_ * chirps_per_frame_ * num_rx_channels_,
        std::complex<std::int16_t>(0, 0));

    for (size_t i = 0; i < in_vector[0].size(); i++) {
        size_t idx = i * 2;
        out_vector[idx].imag(in_vector[0][i]);
        out_vector[idx + 1].imag(in_vector[1][i]);
        out_vector[idx].real(in_vector[2][i]);
        out_vector[idx + 1].real(in_vector[3][i]);
    }
    return out_vector;
}

// IWR1443 (SDK 2): interleaved format — real and imaginary stored in separate Rx-grouped rows
void ADCCubeConverter::fill_interleaved(const std::vector<uint8_t>& frame_bytes)
{
    std::vector<std::int16_t> adc_ints = convert_from_bytes_to_ints(frame_bytes);
    std::vector<std::vector<std::int16_t>> reshaped = reshape_to_2D(
        adc_ints, num_rx_channels_ * 2);

    for (size_t chirp = 0; chirp < chirps_per_frame_; chirp++) {
        for (size_t sample = 0; sample < samples_per_chirp_; sample++) {
            size_t idx = chirp * samples_per_chirp_ + sample;
            for (size_t rx = 0; rx < num_rx_channels_; rx++) {
                cube_[rx][sample][chirp].real(reshaped[rx][idx]);
                cube_[rx][sample][chirp].imag(reshaped[rx + num_rx_channels_][idx]);
            }
        }
    }
}

// IWR1843 / IWR6843 (SDK 3+): non-interleaved format — 4 LVDS lanes with I/Q pairs
void ADCCubeConverter::fill_noninterleaved(const std::vector<uint8_t>& frame_bytes)
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
