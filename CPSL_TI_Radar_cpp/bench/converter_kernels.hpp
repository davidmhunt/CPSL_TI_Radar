// Bench-local ADC converter kernels for bench_pipeline (directive core-09).
//
// These exist ONLY to put numbers on design decision D5 (nested vs flat
// AdcFrame). They are not driver code and nothing in src/ uses them.
//
// All three variants decode the same wire format as today's
// ADCCubeConverter::fill_noninterleaved (IWR1843/IWR6843, lvds.layout
// two_lane_iq_pairs, iq_order q_first): the byte stream is little-endian
// int16 words, chirp-major then Rx then sample, and every group of four words
// [w0 w1 w2 w3] carries two consecutive samples as
//     sample k   = complex(real = w2, imag = w0)
//     sample k+1 = complex(real = w3, imag = w1)
// (ADCCubeConverter.cpp interleave_data). Equivalence with variant (a) is
// checked at bench start-up on random data.
#ifndef BENCH_CONVERTER_KERNELS_HPP
#define BENCH_CONVERTER_KERNELS_HPP

#include <complex>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "ADCCubeConverter.hpp"

namespace bench {

using Sample = std::complex<std::int16_t>;
using NestedCube = std::vector<std::vector<std::vector<Sample>>>;  // [rx][sample][chirp]

struct FrameShape {
    size_t rx = 0, samples = 0, chirps = 0;
    size_t bytes() const { return rx * samples * chirps * 4; }
};

// Read element (rx, sample, chirp) from whatever layout a kernel produces.
class Kernel {
public:
    virtual ~Kernel() {}
    virtual const char* id() const = 0;
    virtual const char* label() const = 0;
    virtual void configure(const FrameShape& s) = 0;  // allocations here are not timed
    virtual void convert(const std::vector<uint8_t>& frame_bytes) = 0;
    virtual Sample at(size_t rx, size_t sample, size_t chirp) const = 0;
    virtual const void* data_ptr() const = 0;  // for the optimizer barrier
};

// (a) today's converter, unchanged, called the way DCA1000Handler calls it:
//     adc_data_cube = converter_.convert(assembler_.get_frame_bytes());
class TodayKernel : public Kernel {
public:
    const char* id() const override { return "a"; }
    const char* label() const override { return "today ADCCubeConverter"; }
    void configure(const FrameShape& s) override {
        conv_.configure(s.rx, s.samples, s.chirps, cpsl::radar::LvdsLayout::two_lane_iq_pairs,
                        cpsl::radar::IqOrder::q_first);  // IWR1843 descriptor
        out_ = NestedCube(s.rx, std::vector<std::vector<Sample>>(s.samples, std::vector<Sample>(s.chirps)));
    }
    void convert(const std::vector<uint8_t>& b) override { out_ = conv_.convert(b); }
    Sample at(size_t r, size_t s, size_t c) const override { return out_[r][s][c]; }
    const void* data_ptr() const override { return &out_; }

private:
    ADCCubeConverter conv_;
    NestedCube out_;
};

// (b) nested [rx][sample][chirp], buffer allocated once and reused; one pass
//     over the bytes (sequential reads, strided writes: chirp is innermost).
class NestedReusedKernel : public Kernel {
public:
    const char* id() const override { return "b"; }
    const char* label() const override { return "nested, reused buffer"; }
    void configure(const FrameShape& s) override {
        s_ = s;
        cube_ = NestedCube(s.rx, std::vector<std::vector<Sample>>(s.samples, std::vector<Sample>(s.chirps)));
    }
    void convert(const std::vector<uint8_t>& b) override {
        const uint8_t* p = b.data();
        for (size_t c = 0; c < s_.chirps; c++) {
            for (size_t r = 0; r < s_.rx; r++) {
                std::vector<std::vector<Sample>>& rx = cube_[r];
                for (size_t s = 0; s < s_.samples; s += 2) {
                    std::int16_t w[4];
                    std::memcpy(w, p, sizeof w);
                    p += sizeof w;
                    rx[s][c] = Sample(w[2], w[0]);
                    rx[s + 1][c] = Sample(w[3], w[1]);
                }
            }
        }
    }
    Sample at(size_t r, size_t s, size_t c) const override { return cube_[r][s][c]; }
    const void* data_ptr() const override { return &cube_; }

private:
    FrameShape s_;
    NestedCube cube_;
};

// (c) flat contiguous [chirp][rx][sample], allocated once; this is the wire
//     order, so the pass is sequential on both sides.
class FlatKernel : public Kernel {
public:
    const char* id() const override { return "c"; }
    const char* label() const override { return "flat [chirp][rx][sample]"; }
    void configure(const FrameShape& s) override {
        s_ = s;
        flat_.assign(s.rx * s.samples * s.chirps, Sample(0, 0));
    }
    void convert(const std::vector<uint8_t>& b) override {
        const uint8_t* p = b.data();
        Sample* o = flat_.data();
        const size_t n = flat_.size();
        for (size_t k = 0; k < n; k += 2) {
            std::int16_t w[4];
            std::memcpy(w, p, sizeof w);
            p += sizeof w;
            o[k] = Sample(w[2], w[0]);
            o[k + 1] = Sample(w[3], w[1]);
        }
    }
    Sample at(size_t r, size_t s, size_t c) const override {
        return flat_[(c * s_.rx + r) * s_.samples + s];
    }
    const void* data_ptr() const override { return flat_.data(); }

private:
    FrameShape s_;
    std::vector<Sample> flat_;
};

}  // namespace bench

#endif  // BENCH_CONVERTER_KERNELS_HPP
