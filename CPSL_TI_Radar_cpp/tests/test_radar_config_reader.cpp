// RadarConfigReader: parse TI .cfg files and derive per-frame sizes.
#include "test_harness.hpp"
#include "RadarConfigReader.hpp"

#include <stdexcept>

static std::string cfg(const char* name) {
    return std::string(TEST_DATA_DIR) + "/radar/" + name;
}

struct Expected {
    const char* file;
    size_t rx, samples, chirps, bytes;
    float period_ms;
};

// cfg dialects from the board descriptors (cfg_dialect.rx_mask_fields /
// frame_period_field): single-chip SDK demos, and the AWR2243 cascade
static const std::vector<uint32_t> kSingleRxFields{1};
static const std::vector<uint32_t> kCascadeRxFields{1, 4};

static void check_cfg(const Expected& e, const std::vector<uint32_t>& rx_fields = kSingleRxFields,
                      uint32_t period_field = 5) {
    RadarConfigReader r(cfg(e.file), rx_fields, period_field);
    CHECK(r.initialized);
    CHECK_EQ(r.get_num_rx_antennas(), e.rx);
    CHECK_EQ(r.get_samples_per_chirp(), e.samples);
    CHECK_EQ(r.get_chirps_per_frame(), e.chirps);
    CHECK_EQ(r.get_bytes_per_frame(), e.bytes);
    CHECK_NEAR(r.get_frame_period_ms(), e.period_ms, 1e-4);
}

// bytes/frame = 4 bytes per complex sample * rx * samples * chirps
TEST_CASE(iwr1443_cfg) {
    // chirps = (2-0+1 chirp slots) * 16 loops = 48
    check_cfg({"iwr1443.cfg", 4, 256, 48, 4 * 4 * 256 * 48, 75.0f});
}

TEST_CASE(iwr1843_cfg) {
    // chirps = (1-0+1) * 115 = 230
    check_cfg({"iwr1843.cfg", 4, 63, 230, 4 * 4 * 63 * 230, 100.0f});
}

TEST_CASE(iwr6843_cfg) {
    // chirps = (2-0+1) * 100 = 300
    check_cfg({"iwr6843.cfg", 4, 63, 300, 4 * 4 * 63 * 300, 100.0f});
}

TEST_CASE(cascade_cfg_numAdcSamples_variant) {
    // cascade dialect: channelCfg master+slave rx masks (fields 1 and 4: 4+4);
    // frameCfg period in field 6 (field 5 is numAdcSamples=192).
    // chirps = (7-0+1) * 32 = 256
    check_cfg({"awr2243_cascade.cfg", 8, 192, 256, 4 * 8 * 192 * 256, 50.0f}, kCascadeRxFields, 6);
}

TEST_CASE(dialect_comes_from_the_caller_not_the_field_count) {
    // The v1 reader guessed the cascade layout from the line lengths. Now the
    // board descriptor decides: read as a single-chip cfg, the same file gives
    // the master mask only and field 5 (numAdcSamples) as the period.
    RadarConfigReader r(cfg("awr2243_cascade.cfg"));
    CHECK(r.initialized);
    CHECK_EQ(r.get_num_rx_antennas(), static_cast<size_t>(4));
    CHECK_NEAR(r.get_frame_period_ms(), 192.0, 1e-4);
    // a listed rx-mask field past the end of the line is not counted
    RadarConfigReader s(cfg("iwr1843.cfg"), kCascadeRxFields, 5);
    CHECK_EQ(s.get_num_rx_antennas(), static_cast<size_t>(4));
}

TEST_CASE(single_rx_channel_mask) {
    check_cfg({"one_rx.cfg", 1, 128, 10, 4 * 1 * 128 * 10, 200.0f});
}

TEST_CASE(rx_defaults_to_four_without_channelCfg) {
    check_cfg({"no_channelcfg.cfg", 4, 128, 10, 4 * 4 * 128 * 10, 200.0f});
}

TEST_CASE(leading_space_line_is_ignored) {
    // Characterization of an oddity: " channelCfg 1 1 0" has an empty key, so the
    // Rx mask is never read and rx stays at the default of 4.
    RadarConfigReader r(cfg("indented_channelcfg.cfg"));
    CHECK(r.initialized);
    CHECK_EQ(r.get_num_rx_antennas(), static_cast<size_t>(4));
}

TEST_CASE(last_profile_and_frame_line_wins) {
    // channelCfg 15 -> 4 rx; second profile: 256 samples; second frameCfg:
    // (1-0+1)*20 = 40 chirps, 50 ms
    check_cfg({"two_profiles.cfg", 4, 256, 40, 4 * 4 * 256 * 40, 50.0f});
}

TEST_CASE(missing_file_is_not_initialized) {
    RadarConfigReader r(cfg("does_not_exist.cfg"));
    CHECK(!r.initialized);
}

TEST_CASE(default_constructed_is_not_initialized) {
    RadarConfigReader r;
    CHECK(!r.initialized);
}

TEST_CASE(reinitialize_after_failure) {
    RadarConfigReader r;
    r.initialize(cfg("does_not_exist.cfg"));
    CHECK(!r.initialized);
    r.initialize(cfg("iwr1843.cfg"));
    CHECK(r.initialized);
    CHECK_EQ(r.get_samples_per_chirp(), static_cast<size_t>(63));
    r.initialize(cfg("does_not_exist.cfg"));
    CHECK(!r.initialized);
}

TEST_CASE(non_numeric_field_throws) {
    // Characterization: malformed numbers escape as std::invalid_argument
    // (std::stoi) instead of leaving initialized == false.
    CHECK_THROWS(RadarConfigReader r(cfg("bad_number.cfg")), std::invalid_argument);
}

TEST_CASE(short_framecfg_is_an_error_not_ub) {
    // core-10 review S4: the period field (5 here) is past the end of the line
    RadarConfigReader r(cfg("short_framecfg.cfg"));
    CHECK(!r.initialized);
    CHECK(r.get_error().find("frameCfg") != std::string::npos);
    CHECK(r.get_error().find("field 5") != std::string::npos);
    // field 6 (cascade dialect) exists on a full single-chip line
    RadarConfigReader c(cfg("iwr1843.cfg"), kSingleRxFields, 6);
    CHECK(c.initialized);
    RadarConfigReader d(cfg("short_framecfg.cfg"), kSingleRxFields, 4);
    CHECK(d.initialized);  // field 4 exists (numFrames)
}

TEST_CASE(copy_and_assignment_preserve_values) {
    RadarConfigReader a(cfg("awr2243_cascade.cfg"), kCascadeRxFields, 6);
    RadarConfigReader b(a);
    CHECK(b.initialized);
    CHECK_EQ(b.get_bytes_per_frame(), a.get_bytes_per_frame());
    CHECK_NEAR(b.get_frame_period_ms(), 50.0, 1e-4);

    RadarConfigReader c;
    c = a;
    CHECK(c.initialized);
    CHECK_EQ(c.get_chirps_per_frame(), static_cast<size_t>(256));
    CHECK_EQ(c.get_num_rx_antennas(), static_cast<size_t>(8));
}

TEST_MAIN()
