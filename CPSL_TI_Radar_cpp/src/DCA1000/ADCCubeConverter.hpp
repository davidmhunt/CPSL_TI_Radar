#ifndef ADCCUBECONVERTER_H
#define ADCCUBECONVERTER_H

// Converts an assembled frame byte buffer into a 3D ADC data cube
// indexed [Rx channel][sample][chirp] as complex<int16_t>.
//
// The layout comes from the board descriptor (lvds.layout, lvds.iq_order):
//   lane_per_rx       (IWR1443 / SDK 2, interleaved): all Rx samples
//                      multiplexed; the two components are stored in separate
//                      Rx-grouped rows.
//   two_lane_iq_pairs (IWR1843, IWR6843 / SDK 3+, non-interleaved): two LVDS
//                      lanes, four int16 words per two samples; the words are
//                      paired into complex values.
//   iq_order says which component comes first on the wire. The shipped
//   descriptors keep the v1 behaviour: lane_per_rx i_first, two_lane_iq_pairs
//   q_first (design §1; core-17 settles it from a bench capture).
//
// Call configure() once after the radar parameters are known, then convert()
// for each received frame.

#include <vector>
#include <complex>
#include <cstdint>
#include <string>

#include "BoardDescriptor.hpp"

class ADCCubeConverter {
public:
    using ADCCube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>;

    void configure(size_t num_rx, size_t samples_per_chirp,
                   size_t chirps_per_frame, cpsl::radar::LvdsLayout layout,
                   cpsl::radar::IqOrder iq_order);

    // Returns the filled ADC cube for the given frame bytes.
    ADCCube convert(const std::vector<uint8_t>& frame_bytes);

private:
    size_t num_rx_channels_ = 0;
    size_t samples_per_chirp_ = 0;
    size_t chirps_per_frame_ = 0;
    cpsl::radar::LvdsLayout layout_ = cpsl::radar::LvdsLayout::two_lane_iq_pairs;
    cpsl::radar::IqOrder iq_order_ = cpsl::radar::IqOrder::q_first;
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
