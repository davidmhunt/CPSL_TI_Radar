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
// for each received frame. convert(bytes, out) writes into a caller-owned
// (pooled) cube; it is (re)shaped only if its shape is wrong, so a reused
// buffer is not reallocated. The conversion is one pass over the packed
// bytes in output order (rx, sample, chirp): writes are sequential along each
// cube[rx][sample] vector, reads stride through the frame. No intermediate
// buffer and no allocation per frame (core-14 P3). A frame shorter than the
// configured shape reads the missing words as 0.

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

    // Fill `out` (every element) with the given frame bytes.
    void convert(const std::vector<uint8_t>& frame_bytes, ADCCube& out);

    // Convenience: a new cube filled with the given frame bytes (allocates).
    ADCCube convert(const std::vector<uint8_t>& frame_bytes);

    // The frame in adc_data.bin order: for chirp, for rx, for sample, the
    // int16 real then imag part (the same values convert() puts in the cube,
    // missing words of a short frame as 0). One sequential pass over the
    // packed bytes; `out` is resized to 2 * rx * samples * chirps (no
    // allocation once it has that size). The driver writes it with a single
    // write() per frame (core-14 P9).
    void file_order(const std::vector<uint8_t>& frame_bytes, std::vector<std::int16_t>& out) const;

    // Give `cube` the configured [rx][sample][chirp] shape; no allocation
    // when it already has it.
    void shape(ADCCube& cube) const;

private:
    size_t num_rx_channels_ = 0;
    size_t samples_per_chirp_ = 0;
    size_t chirps_per_frame_ = 0;
    cpsl::radar::LvdsLayout layout_ = cpsl::radar::LvdsLayout::two_lane_iq_pairs;
    cpsl::radar::IqOrder iq_order_ = cpsl::radar::IqOrder::q_first;

    void fill_interleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube);
    void fill_noninterleaved(const std::vector<uint8_t>& frame_bytes, ADCCube& cube);
};

#endif // ADCCUBECONVERTER_H
