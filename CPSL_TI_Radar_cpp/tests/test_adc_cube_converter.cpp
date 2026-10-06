// ADCCubeConverter: frame bytes -> [rx][sample][chirp] complex<int16> cube.
//
// Each test builds the raw stream from a known cube using the wire layout the
// converter implements today, then checks the round trip.
#include "test_harness.hpp"
#include "ADCCubeConverter.hpp"

using cpsl::radar::IqOrder;
using cpsl::radar::LvdsLayout;

// the shipped descriptors' (lvds.layout, lvds.iq_order)
#define IWR1443_LVDS LvdsLayout::lane_per_rx, IqOrder::i_first
#define IWR18_68_LVDS LvdsLayout::two_lane_iq_pairs, IqOrder::q_first

typedef std::vector<uint8_t> Bytes;
typedef std::complex<std::int16_t> Cx;

static void put_i16(Bytes& b, int16_t v) {
    uint16_t u = static_cast<uint16_t>(v);
    b.push_back(static_cast<uint8_t>(u & 0xFF));
    b.push_back(static_cast<uint8_t>(u >> 8));
}

// distinct, sign-varying value for every cube cell; `salt` varies the frame
static Cx value(size_t rx, size_t s, size_t c, int salt = 0) {
    return Cx(static_cast<int16_t>(1000 * static_cast<int>(rx + 1) + 10 * static_cast<int>(s) +
                                   static_cast<int>(c) + salt),
              static_cast<int16_t>(-(2000 * static_cast<int>(rx + 1) + 10 * static_cast<int>(s) +
                                     static_cast<int>(c)) - salt));
}

// IWR1443 (interleaved): per (chirp, sample) one group of [re rx0..rxN-1, im rx0..rxN-1]
static Bytes interleaved_stream(size_t rx, size_t samples, size_t chirps, int salt = 0) {
    Bytes b;
    for (size_t c = 0; c < chirps; c++)
        for (size_t s = 0; s < samples; s++) {
            for (size_t r = 0; r < rx; r++) put_i16(b, value(r, s, c, salt).real());
            for (size_t r = 0; r < rx; r++) put_i16(b, value(r, s, c, salt).imag());
        }
    return b;
}

// IWR1843/6843 (non-interleaved): per (chirp, rx), sample pairs (2k, 2k+1) as
// [Im(2k), Im(2k+1), Re(2k), Re(2k+1)]
static Bytes noninterleaved_stream(size_t rx, size_t samples, size_t chirps, int salt = 0) {
    Bytes b;
    for (size_t c = 0; c < chirps; c++)
        for (size_t r = 0; r < rx; r++)
            for (size_t k = 0; k < samples / 2; k++) {
                put_i16(b, value(r, 2 * k, c, salt).imag());
                put_i16(b, value(r, 2 * k + 1, c, salt).imag());
                put_i16(b, value(r, 2 * k, c, salt).real());
                put_i16(b, value(r, 2 * k + 1, c, salt).real());
            }
    return b;
}

static void check_cube(const ADCCubeConverter::ADCCube& cube, size_t rx, size_t samples,
                       size_t chirps, int salt = 0) {
    CHECK_EQ(cube.size(), rx);
    if (cube.size() != rx) return;
    for (size_t r = 0; r < rx; r++) {
        CHECK_EQ(cube[r].size(), samples);
        for (size_t s = 0; s < samples; s++) {
            CHECK_EQ(cube[r][s].size(), chirps);
            for (size_t c = 0; c < chirps; c++) {
                if (cube[r][s][c] != value(r, s, c, salt)) {
                    th::fail(__FILE__, __LINE__,
                             "cube mismatch at rx=" + std::to_string(r) + " sample=" +
                                 std::to_string(s) + " chirp=" + std::to_string(c) + " got " +
                                 th::show(cube[r][s][c]) + " want " +
                                 th::show(value(r, s, c, salt)));
                    return;
                }
                th::counters().checks++;
            }
        }
    }
}

TEST_CASE(iwr1443_interleaved_four_rx) {
    ADCCubeConverter conv;
    conv.configure(4, 8, 3, IWR1443_LVDS);
    check_cube(conv.convert(interleaved_stream(4, 8, 3)), 4, 8, 3);
}

TEST_CASE(iwr1443_interleaved_two_rx) {
    ADCCubeConverter conv;
    conv.configure(2, 5, 4, IWR1443_LVDS);  // odd sample count is fine when interleaved
    check_cube(conv.convert(interleaved_stream(2, 5, 4)), 2, 5, 4);
}

TEST_CASE(iwr1843_noninterleaved_four_rx) {
    ADCCubeConverter conv;
    conv.configure(4, 8, 3, IWR18_68_LVDS);
    check_cube(conv.convert(noninterleaved_stream(4, 8, 3)), 4, 8, 3);
}

TEST_CASE(iwr6843_uses_noninterleaved_path) {
    ADCCubeConverter conv;
    conv.configure(4, 6, 5, IWR18_68_LVDS);
    check_cube(conv.convert(noninterleaved_stream(4, 6, 5)), 4, 6, 5);
}

TEST_CASE(noninterleaved_single_rx_and_two_rx) {
    ADCCubeConverter one;
    one.configure(1, 4, 2, IWR18_68_LVDS);
    check_cube(one.convert(noninterleaved_stream(1, 4, 2)), 1, 4, 2);
    ADCCubeConverter two;
    two.configure(2, 4, 3, IWR18_68_LVDS);
    check_cube(two.convert(noninterleaved_stream(2, 4, 3)), 2, 4, 3);
}

TEST_CASE(int16_extremes_and_sign_survive) {
    ADCCubeConverter conv;
    conv.configure(1, 2, 1, IWR18_68_LVDS);
    // one pair: Im0 Im1 Re0 Re1
    Bytes b;
    put_i16(b, -32768);
    put_i16(b, 32767);
    put_i16(b, -1);
    put_i16(b, 1);
    auto cube = conv.convert(b);
    CHECK(cube[0][0][0] == Cx(-1, -32768));
    CHECK(cube[0][1][0] == Cx(1, 32767));
}

TEST_CASE(wire_order_is_little_endian) {
    ADCCubeConverter conv;
    conv.configure(1, 1, 1, IWR1443_LVDS);
    // interleaved, 1 rx: [re, im]; re = 0x0102, im = 0x0304 sent low byte first
    Bytes b{0x02, 0x01, 0x04, 0x03};
    auto cube = conv.convert(b);
    CHECK(cube[0][0][0] == Cx(0x0102, 0x0304));
}

TEST_CASE(consecutive_frames_fully_overwrite_the_cube) {
    ADCCubeConverter conv;
    conv.configure(4, 4, 2, IWR18_68_LVDS);
    check_cube(conv.convert(noninterleaved_stream(4, 4, 2, 0)), 4, 4, 2, 0);
    check_cube(conv.convert(noninterleaved_stream(4, 4, 2, 7)), 4, 4, 2, 7);
}

TEST_CASE(iq_order_swaps_components_on_both_layouts) {
    // The opposite iq_order of each shipped layout reads the same bytes with
    // real and imaginary exchanged (core-17 may flip a descriptor to this).
    {
        ADCCubeConverter conv;
        conv.configure(4, 8, 3, LvdsLayout::two_lane_iq_pairs, IqOrder::i_first);
        auto cube = conv.convert(noninterleaved_stream(4, 8, 3));
        bool swapped = true;
        for (size_t r = 0; r < 4; r++)
            for (size_t s = 0; s < 8; s++)
                for (size_t c = 0; c < 3; c++) {
                    Cx want = value(r, s, c);
                    if (cube[r][s][c] != Cx(want.imag(), want.real())) swapped = false;
                }
        CHECK(swapped);
    }
    {
        ADCCubeConverter conv;
        conv.configure(2, 5, 4, LvdsLayout::lane_per_rx, IqOrder::q_first);
        auto cube = conv.convert(interleaved_stream(2, 5, 4));
        bool swapped = true;
        for (size_t r = 0; r < 2; r++)
            for (size_t s = 0; s < 5; s++)
                for (size_t c = 0; c < 4; c++) {
                    Cx want = value(r, s, c);
                    if (cube[r][s][c] != Cx(want.imag(), want.real())) swapped = false;
                }
        CHECK(swapped);
    }
}

TEST_CASE(configure_sizes_cube_before_first_frame) {
    // an empty frame on the 2-lane path returns the zeroed, fully sized cube
    ADCCubeConverter conv;
    conv.configure(3, 8, 2, IWR18_68_LVDS);
    auto cube = conv.convert(Bytes());
    CHECK_EQ(cube.size(), static_cast<size_t>(3));
    CHECK_EQ(cube[0].size(), static_cast<size_t>(8));
    CHECK_EQ(cube[0][0].size(), static_cast<size_t>(2));
    CHECK(cube[2][7][1] == Cx(0, 0));
}

// IWR1843/6843 with an odd sample count per (chirp, rx): the word groups pair
// consecutive samples of the whole frame, n = (chirp * rx + r) * samples + s,
// so a pair may straddle two (chirp, rx) blocks (the v1 converter paired the
// same way)
static Bytes noninterleaved_global_stream(size_t rx, size_t samples, size_t chirps) {
    Bytes b;
    const size_t total = rx * samples * chirps;
    auto at = [&](size_t n) {
        const size_t c = n / (rx * samples), r = (n / samples) % rx, s = n % samples;
        return value(r, s, c);
    };
    for (size_t n = 0; n + 1 < total; n += 2) {
        put_i16(b, at(n).imag());
        put_i16(b, at(n + 1).imag());
        put_i16(b, at(n).real());
        put_i16(b, at(n + 1).real());
    }
    return b;
}

TEST_CASE(noninterleaved_pairs_straddle_blocks_when_samples_are_odd) {
    ADCCubeConverter conv;
    conv.configure(1, 3, 4, IWR18_68_LVDS);  // 3 samples per (chirp, rx): odd
    check_cube(conv.convert(noninterleaved_global_stream(1, 3, 4)), 1, 3, 4);
    ADCCubeConverter three;
    three.configure(3, 5, 2, IWR18_68_LVDS);  // 15 samples per chirp, 30 per frame
    check_cube(three.convert(noninterleaved_global_stream(3, 5, 2)), 3, 5, 2);
}

TEST_CASE(short_frame_reads_missing_words_as_zero_on_both_layouts) {
    {
        ADCCubeConverter conv;
        conv.configure(2, 4, 3, IWR18_68_LVDS);
        Bytes b = noninterleaved_stream(2, 4, 3);
        b.resize(b.size() / 2);  // chirp 0 and half of chirp 1
        ADCCubeConverter::ADCCube cube(2, std::vector<std::vector<Cx>>(4, std::vector<Cx>(3, Cx(9, 9))));
        conv.convert(b, cube);
        CHECK(cube[0][0][0] == value(0, 0, 0));
        CHECK(cube[1][3][0] == value(1, 3, 0));
        CHECK(cube[0][3][1] == value(0, 3, 1));
        CHECK(cube[1][0][1] == Cx(0, 0));
        CHECK(cube[1][3][2] == Cx(0, 0));
    }
    {
        ADCCubeConverter conv;
        conv.configure(2, 3, 2, IWR1443_LVDS);
        Bytes b = interleaved_stream(2, 3, 2);
        b.resize(b.size() / 2);  // chirp 0 only
        auto cube = conv.convert(b);
        CHECK(cube[1][2][0] == value(1, 2, 0));
        CHECK(cube[0][0][1] == Cx(0, 0));
    }
}

// adc_data.bin order (core-14 P9): for chirp, rx, sample: real, imag. It
// must hold exactly the cube's values, which is what the v1 per-element
// writer put in the file.
static void check_file_order(ADCCubeConverter& conv, const Bytes& b, size_t rx, size_t samples, size_t chirps) {
    const auto cube = conv.convert(b);
    std::vector<int16_t> file;
    conv.file_order(b, file);
    CHECK_EQ(file.size(), 2 * rx * samples * chirps);
    size_t i = 0, bad = 0;
    for (size_t c = 0; c < chirps; c++)
        for (size_t r = 0; r < rx; r++)
            for (size_t s = 0; s < samples; s++) {
                if (i + 1 >= file.size() || file[i] != cube[r][s][c].real() || file[i + 1] != cube[r][s][c].imag()) bad++;
                i += 2;
            }
    CHECK_EQ(bad, size_t(0));
}

TEST_CASE(file_order_matches_the_cube_on_every_layout) {
    for (int iq = 0; iq < 2; iq++) {
        const IqOrder order = iq == 0 ? IqOrder::q_first : IqOrder::i_first;
        ADCCubeConverter two;
        two.configure(4, 8, 3, LvdsLayout::two_lane_iq_pairs, order);
        check_file_order(two, noninterleaved_stream(4, 8, 3), 4, 8, 3);
        ADCCubeConverter odd;
        odd.configure(3, 5, 2, LvdsLayout::two_lane_iq_pairs, order);
        check_file_order(odd, noninterleaved_global_stream(3, 5, 2), 3, 5, 2);
        Bytes shortb = noninterleaved_stream(4, 8, 3);
        shortb.resize(shortb.size() / 3);
        check_file_order(two, shortb, 4, 8, 3);
        ADCCubeConverter lane;
        lane.configure(2, 5, 4, LvdsLayout::lane_per_rx, order);
        check_file_order(lane, interleaved_stream(2, 5, 4), 2, 5, 4);
        Bytes shortl = interleaved_stream(2, 5, 4);
        shortl.resize(shortl.size() / 2 + 2);
        check_file_order(lane, shortl, 2, 5, 4);
    }
    // on the shipped IWR1843 path the file is the wire bytes with each
    // four-word group reordered [A0 A1 B0 B1] -> [B0 A0 B1 A1]
    ADCCubeConverter conv;
    conv.configure(1, 2, 1, IWR18_68_LVDS);
    Bytes b;
    for (int16_t v : {11, 12, 21, 22}) put_i16(b, v);
    std::vector<int16_t> file;
    conv.file_order(b, file);
    CHECK(file == std::vector<int16_t>({21, 11, 22, 12}));
}

TEST_CASE(convert_into_a_reused_buffer_keeps_its_storage) {
    // design P2: the driver converts into pooled cubes; a correctly shaped
    // buffer is filled in place (same storage), a wrongly shaped one is
    // reshaped once
    for (int layout = 0; layout < 2; layout++) {
        ADCCubeConverter conv;
        const bool two_lane = layout == 0;
        if (two_lane) conv.configure(4, 8, 3, IWR18_68_LVDS);
        else conv.configure(2, 5, 4, IWR1443_LVDS);
        const size_t rx = two_lane ? 4 : 2, samples = two_lane ? 8 : 5, chirps = two_lane ? 3 : 4;
        auto stream = [&](int salt) {
            return two_lane ? noninterleaved_stream(rx, samples, chirps, salt)
                            : interleaved_stream(rx, samples, chirps, salt);
        };
        ADCCubeConverter::ADCCube cube;  // empty: the first convert shapes it
        conv.convert(stream(0), cube);
        check_cube(cube, rx, samples, chirps, 0);
        std::vector<const Cx*> storage;
        for (const auto& r : cube)
            for (const auto& s : r) storage.push_back(s.data());
        conv.convert(stream(5), cube);
        check_cube(cube, rx, samples, chirps, 5);
        size_t i = 0;
        bool same = true;
        for (const auto& r : cube)
            for (const auto& s : r) same = same && s.data() == storage[i++];
        CHECK(same);
        // a buffer of another shape (e.g. handed back by a consumer) is reshaped
        ADCCubeConverter::ADCCube odd(1, std::vector<std::vector<Cx>>(2, std::vector<Cx>(9, Cx(7, 7))));
        conv.convert(stream(3), odd);
        check_cube(odd, rx, samples, chirps, 3);
    }
}

TEST_MAIN()
