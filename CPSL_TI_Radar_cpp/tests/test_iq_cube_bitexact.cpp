// ADCCubeConverter output on the tracked raw frame must equal, bit for bit, the cube that the
// doc-only decoder docs/raw_data/decode_example.py produces from the same bytes (golden:
// tests/data/iq/iwr1843_R0.9m_frame99.cube_int16.bin = int16 [rx][sample][chirp][re,im], little-endian).
// Regenerate the golden only from decode_example.py (see tests/test_raw_data_doc.py), never from the converter.
#include <cstring>
#include <fstream>
#include <iostream>
#include "test_harness.hpp"
#include "ADCCubeConverter.hpp"
#include "BoardDescriptor.hpp"

using cpsl::radar::BoardDescriptor;

static const size_t kRx = 4, kSamples = 128, kChirps = 256;  // bench_1843_dca.cfg, as test_iq_golden.cpp

static std::vector<uint8_t> slurp(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

TEST_CASE(converter_cube_equals_doc_decoder_golden) {
    BoardDescriptor d;
    std::string err;
    CHECK(BoardDescriptor::load_by_name(std::string(CONFIG_DIR) + "/boards", "IWR1843", d, err));
    const std::string dir = std::string(TEST_DATA_DIR) + "/iq/";
    const std::vector<uint8_t> raw = slurp(dir + "iwr1843_R0.9m_frame99.bin");
    const std::vector<uint8_t> gold = slurp(dir + "iwr1843_R0.9m_frame99.cube_int16.bin");
    CHECK_EQ(raw.size(), 4 * kRx * kSamples * kChirps);
    CHECK_EQ(gold.size(), 4 * kRx * kSamples * kChirps);

    ADCCubeConverter conv;
    conv.configure(kRx, kSamples, kChirps, d.lvds.layout, d.lvds.iq_order);
    ADCCubeConverter::ADCCube cube = conv.convert(raw);  // [rx][sample][chirp]

    size_t i = 0, bad = 0, first = 0;
    for (size_t r = 0; r < kRx; r++)
        for (size_t s = 0; s < kSamples; s++)
            for (size_t c = 0; c < kChirps; c++) {
                int16_t g[2];
                std::memcpy(g, &gold[i * 4], 4);  // host is little-endian, like the golden
                const int16_t re = static_cast<int16_t>(cube[r][s][c].real());
                const int16_t im = static_cast<int16_t>(cube[r][s][c].imag());
                if (re != g[0] || im != g[1]) {
                    if (bad++ == 0) {
                        first = i;
                        std::cerr << "first mismatch at rx " << r << " sample " << s << " chirp " << c
                                  << ": converter (" << re << "," << im << ") golden (" << g[0] << "," << g[1] << ")\n";
                    }
                }
                i++;
            }
    std::cerr << "compared " << i << " samples, " << bad << " differ (first index " << first << ")\n";
    CHECK_EQ(bad, static_cast<size_t>(0));
}

TEST_MAIN()
