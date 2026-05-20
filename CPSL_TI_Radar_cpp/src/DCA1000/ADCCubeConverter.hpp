#ifndef ADCCUBECONVERTER_H
#define ADCCUBECONVERTER_H

// Converts an assembled frame byte buffer into a 3D ADC data cube
// indexed [Rx channel][sample][chirp] as complex<int16_t>.
//
// Two LVDS lane formats are supported:
//   Interleaved   (IWR1443 / SDK 2): all Rx samples multiplexed; real and
//                  imaginary components stored in separate Rx-grouped rows.
//   Non-interleaved (IWR1843, IWR6843 / SDK 3+): four LVDS lanes carrying
//                  alternating I/Q pairs; lanes are interleaved into complex values.
//
// Call configure() once after the radar parameters are known, then convert()
// for each received frame.

#include <vector>
#include <complex>
#include <cstdint>
#include <string>

class ADCCubeConverter {
public:
    using ADCCube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>;

    void configure(size_t num_rx, size_t samples_per_chirp,
                   size_t chirps_per_frame, const std::string& board_type);

    // Returns the filled ADC cube for the given frame bytes.
    ADCCube convert(const std::vector<uint8_t>& frame_bytes);

private:
    size_t num_rx_channels_ = 0;
    size_t samples_per_chirp_ = 0;
    size_t chirps_per_frame_ = 0;
    std::string board_type_;
    ADCCube cube_;

    std::vector<std::int16_t> convert_from_bytes_to_ints(
        const std::vector<uint8_t>& in_vector);
    std::vector<std::vector<std::int16_t>> reshape_to_2D(
        std::vector<std::int16_t>& in_vector, size_t num_rows);
    std::vector<std::complex<std::int16_t>> interleave_data(
        std::vector<std::vector<std::int16_t>>& in_vector);

    void fill_interleaved(const std::vector<uint8_t>& frame_bytes);
    void fill_noninterleaved(const std::vector<uint8_t>& frame_bytes);
};

#endif // ADCCUBECONVERTER_H
