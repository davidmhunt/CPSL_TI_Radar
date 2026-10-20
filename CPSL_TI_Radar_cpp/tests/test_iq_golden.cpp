// Golden I/Q test: one real raw LVDS frame (IWR1843, stock demo, DCA1000, ~0.9 m reflector,
// tests/data/iq/README.md) through ADCCubeConverter::convert() with the IWR1843 board descriptor's
// layout/iq_order; a chirp-averaged range DFT on rx0 must peak at the reflector's range bin, with its
// mirror bin (N - peak) well below. A flipped iq_order moves the peak to the mirror bin.
#include <cmath>
#include <fstream>
#include <iostream>
#include "test_harness.hpp"
#include "ADCCubeConverter.hpp"
#include "BoardDescriptor.hpp"

using cpsl::radar::BoardDescriptor;
using cpsl::radar::IqOrder;

static const size_t kRx = 4, kSamples = 128, kChirps = 256;  // bench_1843_dca.cfg: channelCfg 15, 128 samples, 2 x 128 loops
static const double kExpectedBin = 10.4;                    // 0.9 m / 0.0868 m per bin
static const int kTolBins = 2;                              // README: peak lands on bin 9 (frame 99)
static const double kMirrorMarginDb = 15.0;

struct Spectrum { size_t peak; double peak_db, mirror_db; };

static std::vector<uint8_t> load_frame() {
    std::ifstream f(std::string(TEST_DATA_DIR) + "/iq/iwr1843_R0.9m_frame99.bin", std::ios::binary);
    std::vector<uint8_t> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    return b;
}

static Spectrum analyse(const std::vector<uint8_t>& bytes, cpsl::radar::LvdsLayout layout, IqOrder order) {
    ADCCubeConverter conv;
    conv.configure(kRx, kSamples, kChirps, layout, order);
    ADCCubeConverter::ADCCube cube = conv.convert(bytes);  // [rx][sample][chirp]
    const double pi = std::acos(-1.0);
    std::vector<double> mag(kSamples, 0.0);
    for (size_t k = 0; k < kSamples; k++)
        for (size_t c = 0; c < kChirps; c++) {  // chirp-averaged magnitude of the DFT over samples
            double re = 0, im = 0;
            for (size_t s = 0; s < kSamples; s++) {
                const double a = -2.0 * pi * static_cast<double>(k * s % kSamples) / kSamples;
                const double xr = cube[0][s][c].real(), xi = cube[0][s][c].imag();
                re += xr * std::cos(a) - xi * std::sin(a);
                im += xr * std::sin(a) + xi * std::cos(a);
            }
            mag[k] += std::sqrt(re * re + im * im) / kChirps;
        }
    Spectrum r{1, 0, 0};
    for (size_t k = 1; k < kSamples / 2; k++)  // positive-frequency half; DC excluded
        if (mag[k] > mag[r.peak]) r.peak = k;
    r.peak_db = 20 * std::log10(mag[r.peak] + 1e-9);
    r.mirror_db = 20 * std::log10(mag[kSamples - r.peak] + 1e-9);
    return r;
}

static bool in_window(size_t bin) { return std::fabs(static_cast<double>(bin) - kExpectedBin) <= kTolBins + 0.5; }

TEST_CASE(iwr1843_descriptor_order_peaks_at_reflector) {
    BoardDescriptor d;
    std::string err;
    CHECK(BoardDescriptor::load_by_name(std::string(CONFIG_DIR) + "/boards", "IWR1843", d, err));
    const std::vector<uint8_t> bytes = load_frame();
    CHECK_EQ(bytes.size(), 4 * kRx * kSamples * kChirps);
    Spectrum s = analyse(bytes, d.lvds.layout, d.lvds.iq_order);
    std::cerr << "peak bin " << s.peak << " " << s.peak_db << " dB, mirror " << s.mirror_db << " dB\n";
    CHECK(in_window(s.peak));
    CHECK(s.peak_db - s.mirror_db >= kMirrorMarginDb);
}

// mutation: the opposite iq_order conjugates the signal, so the peak sits at the mirror bin
TEST_CASE(flipped_iq_order_fails_the_same_assertions) {
    BoardDescriptor d;
    std::string err;
    CHECK(BoardDescriptor::load_by_name(std::string(CONFIG_DIR) + "/boards", "IWR1843", d, err));
    const IqOrder flipped = d.lvds.iq_order == IqOrder::q_first ? IqOrder::i_first : IqOrder::q_first;
    Spectrum s = analyse(load_frame(), d.lvds.layout, flipped);
    std::cerr << "flipped: peak bin " << s.peak << "\n";
    CHECK(!in_window(s.peak));
}

TEST_MAIN()
