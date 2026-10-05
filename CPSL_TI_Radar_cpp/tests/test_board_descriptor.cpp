// BoardDescriptor: strict loading of config/boards/*.json and the radar .cfg
// cross-checks (driver v2 design §1, directive core-09).
//
// Required coverage: the four shipped boards load (4 cases) and six rejection
// cases (unknown key, bad enum, lanes/layout mismatch, and three cfg
// mismatches). Further cases after those pin the rest of the contract.
#include "test_harness.hpp"
#include "BoardDescriptor.hpp"

#include <fstream>
#include <string>

using cpsl::radar::BoardDescriptor;
using cpsl::radar::CfgCheckResult;
using cpsl::radar::IqOrder;
using cpsl::radar::LvdsLayout;
using cpsl::radar::Sdk;
using cpsl::radar::StreamSelection;
using cpsl::radar::TlvDialect;
using nlohmann::json;

static const std::string kBoards = std::string(CONFIG_DIR) + "/boards";

static json read_json(const std::string& path) {
    std::ifstream f(path);
    return json::parse(f);
}

static BoardDescriptor must_load(const std::string& name) {
    BoardDescriptor d;
    std::string err;
    bool ok = BoardDescriptor::load_by_name(kBoards, name, d, err);
    if (!ok) std::cerr << "load failed: " << err << std::endl;
    CHECK(ok);
    return d;
}

// from_json on a shipped board after `mutate`; returns the error ("" if it loaded)
template <class F>
static std::string reject(const std::string& name, F mutate) {
    json j = read_json(kBoards + "/" + name + ".json");
    mutate(j);
    BoardDescriptor d;
    std::string err;
    bool ok = BoardDescriptor::from_json(j, name, "test:" + name, d, err);
    if (ok) return "";
    std::cout << "    rejected as expected: " << err << std::endl;
    return err;
}

static bool has(const std::string& s, const std::string& sub) { return s.find(sub) != std::string::npos; }

static std::string write_cfg(const std::string& name, const std::string& body) {
    std::string path = std::string(TEST_TMP_DIR) + "/" + name;
    std::ofstream f(path);
    f << body;
    return path;
}

static CfgCheckResult check(const BoardDescriptor& b, const std::string& cfg, bool dca, bool serial) {
    StreamSelection s;
    s.dca1000 = dca;
    s.serial = serial;
    CfgCheckResult r = cpsl::radar::cross_check_radar_cfg(b, cfg, s);
    for (const auto& e : r.errors) std::cout << "    error: " << e << std::endl;
    for (const auto& n : r.notes) std::cout << "    note:  " << n << std::endl;
    return r;
}

static bool any_has(const std::vector<std::string>& v, const std::string& sub) {
    for (const auto& s : v)
        if (has(s, sub)) return true;
    return false;
}

// A minimal SDK 3 DCA1000 cfg; each rejection case changes one line.
static std::string sdk3_cfg(const std::string& adc, const std::string& adcbuf, const std::string& lvds) {
    return "% test cfg\nsensorStop\nflushCfg\ndfeDataOutputMode 1\nchannelCfg 15 5 0\n" + adc + "\n" + adcbuf +
           "\nprofileCfg 0 77 7 3 24 0 0 50 1 128 5000 0 0 30\nframeCfg 0 1 16 0 100 1 0\n" + lvds +
           "\nsensorStart\n";
}

// ---------------------------------------------------------------------------
// The four shipped boards (design §1 table)
// ---------------------------------------------------------------------------

TEST_CASE(loads_IWR1443) {
    BoardDescriptor d = must_load("IWR1443");
    CHECK_EQ(d.name, std::string("IWR1443"));
    CHECK(d.sdk == Sdk::mmwave_sdk_2);
    CHECK_EQ(d.cli.cmd_timeout_ms, 100u);
    CHECK(!d.lifecycle.config_once_per_boot);
    CHECK_EQ(d.data_uart.header_bytes, 36u);
    CHECK(d.data_uart.tlv_dialect == TlvDialect::sdk2);
    CHECK(d.lvds.supported);
    CHECK_EQ(d.lvds.lanes, 4u);
    CHECK(d.lvds.layout == LvdsLayout::lane_per_rx);
    CHECK(d.lvds.iq_order == IqOrder::i_first);
    CHECK(d.dca1000.present);
}

TEST_CASE(loads_IWR1843) {
    BoardDescriptor d = must_load("IWR1843");
    CHECK(d.sdk == Sdk::mmwave_sdk_3);
    CHECK_EQ(d.cli.baud, 115200u);
    CHECK_EQ(d.cli.ack, std::string("Done"));
    CHECK_EQ(d.cli.prompt, std::string("mmwDemo:/>"));
    CHECK_EQ(d.cli.prompt_wait_ms, 500u);
    CHECK_EQ(d.cli.start_cmd, std::string("sensorStart"));
    CHECK_EQ(d.cli.stop_cmd, std::string("sensorStop"));
    CHECK_EQ(d.cli.skip_prefixes.size(), static_cast<size_t>(2));
    CHECK_EQ(d.cfg_dialect.rx_mask_fields.size(), static_cast<size_t>(1));
    CHECK_EQ(d.cfg_dialect.rx_mask_fields[0], 1u);
    CHECK_EQ(d.cfg_dialect.frame_period_field, 5u);
    CHECK_EQ(d.data_uart.baud, 921600u);
    CHECK_EQ(d.data_uart.header_bytes, 40u);
    CHECK(d.data_uart.tlv_dialect == TlvDialect::sdk3);
    CHECK_EQ(d.lvds.lanes, 2u);
    CHECK(d.lvds.layout == LvdsLayout::two_lane_iq_pairs);
    CHECK(d.lvds.iq_order == IqOrder::q_first);
    CHECK_EQ(d.dca1000.packet_bytes, 1472u);
    CHECK_EQ(d.dca1000.packet_delay_us, 100u);
    CHECK_EQ(d.dca1000.fpga_timer_s, 30u);
}

TEST_CASE(loads_IWR6843) {
    BoardDescriptor d = must_load("IWR6843");
    CHECK_EQ(d.name, std::string("IWR6843"));
    CHECK(d.sdk == Sdk::mmwave_sdk_3);
    CHECK(d.data_uart.tlv_dialect == TlvDialect::sdk3);
    CHECK_EQ(d.lvds.lanes, 2u);
    CHECK(d.lvds.layout == LvdsLayout::two_lane_iq_pairs);
    CHECK(d.lvds.iq_order == IqOrder::q_first);
}

TEST_CASE(loads_AWR2243_CASCADE) {
    BoardDescriptor d = must_load("AWR2243_CASCADE");
    CHECK(d.sdk == Sdk::mmwave_mcuplus);
    CHECK_EQ(d.cli.cmd_timeout_ms, 5000u);
    CHECK(d.lifecycle.config_once_per_boot);
    CHECK_EQ(d.cfg_dialect.rx_mask_fields.size(), static_cast<size_t>(2));
    CHECK_EQ(d.cfg_dialect.rx_mask_fields[1], 4u);
    CHECK_EQ(d.cfg_dialect.frame_period_field, 6u);
    CHECK_EQ(d.data_uart.baud, 3125000u);
    CHECK(d.data_uart.tlv_dialect == TlvDialect::mcuplus_cascade);
    CHECK(!d.lvds.supported);
    CHECK(!d.dca1000.present);
}

// ---------------------------------------------------------------------------
// The six rejection cases
// ---------------------------------------------------------------------------

TEST_CASE(rejects_unknown_key) {
    std::string e = reject("IWR1843", [](json& j) { j["cli"]["bauds"] = 115200; });
    CHECK(has(e, "/cli/bauds"));
    CHECK(has(e, "unknown key"));
}

TEST_CASE(rejects_bad_enum) {
    std::string e = reject("IWR1843", [](json& j) { j["lvds"]["layout"] = "three_lane"; });
    CHECK(has(e, "/lvds/layout"));
    CHECK(has(e, "\"three_lane\" is not one of"));
}

TEST_CASE(rejects_lanes_layout_mismatch) {
    std::string e = reject("IWR1843", [](json& j) { j["lvds"]["lanes"] = 4; });
    CHECK(has(e, "layout two_lane_iq_pairs needs lanes 2"));
}

TEST_CASE(rejects_cfg_chan_interleave_mismatch) {
    BoardDescriptor d = must_load("IWR1843");
    // chanInterleave 0 = interleaved, which belongs to lane_per_rx (IWR1443)
    std::string cfg = write_cfg("bd_interleaved.cfg",
                                sdk3_cfg("adcCfg 2 1", "adcbufCfg -1 0 1 0 1", "lvdsStreamCfg -1 0 1 0"));
    CfgCheckResult r = check(d, cfg, true, false);
    CHECK(!r.ok());
    CHECK(any_has(r.errors, "chanInterleave 0 (interleaved) needs lvds.layout lane_per_rx"));
}

TEST_CASE(rejects_cfg_real_only_output) {
    BoardDescriptor d = must_load("IWR1843");
    std::string cfg = write_cfg("bd_real.cfg",
                                sdk3_cfg("adcCfg 2 0", "adcbufCfg -1 1 1 1 1", "lvdsStreamCfg -1 0 1 0"));
    CfgCheckResult r = check(d, cfg, true, false);
    CHECK(!r.ok());
    CHECK(any_has(r.errors, "adcCfg: adcOutputFmt 0 is real-only"));
    CHECK(any_has(r.errors, "adcbufCfg: adcOutputFmt 1 is real-only"));
}

TEST_CASE(rejects_cfg_lvds_adc_streaming_disabled) {
    BoardDescriptor d = must_load("IWR1843");
    std::string cfg = write_cfg("bd_nolvds.cfg",
                                sdk3_cfg("adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 0 0"));
    CfgCheckResult r = check(d, cfg, true, false);
    CHECK(!r.ok());
    CHECK(any_has(r.errors, "dataFmt 0 disables LVDS streaming"));
    // the same cfg is fine for serial-only use
    CHECK(check(d, cfg, false, true).ok());
}

// ---------------------------------------------------------------------------
// Further contract
// ---------------------------------------------------------------------------

TEST_CASE(good_sdk3_cfg_passes_without_notes) {
    BoardDescriptor d = must_load("IWR1843");
    std::string cfg = write_cfg("bd_good.cfg",
                                sdk3_cfg("adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 1 0"));
    CfgCheckResult r = check(d, cfg, true, false);
    CHECK(r.ok());
    CHECK(r.notes.empty());
}

TEST_CASE(tracked_baseline_cfg_passes_for_IWR1843_dca) {
    BoardDescriptor d = must_load("IWR1843");
    CfgCheckResult r = check(d, std::string(CONFIG_DIR) + "/radar/nav_configs/1843_stress_test.cfg", true, true);
    CHECK(r.ok());
}

TEST_CASE(sdk2_adcbufcfg_has_no_subframe_field) {
    BoardDescriptor d = must_load("IWR1443");
    // xWR14xx SDK 2 form: adcbufCfg <fmt> <swap> <interleave> <threshold>
    std::string ok_cfg = write_cfg("bd_1443.cfg", "adcCfg 2 1\nadcbufCfg 0 1 0 1\n");
    CfgCheckResult r = check(d, ok_cfg, true, false);
    CHECK(r.ok());
    CHECK(any_has(r.notes, "no lvdsStreamCfg line"));
    // the SDK 3 form on an SDK 2 board is a field-count error, not silently misread
    std::string bad_cfg = write_cfg("bd_1443_sdk3form.cfg", "adcCfg 2 1\nadcbufCfg -1 0 1 0 1\n");
    CHECK(any_has(check(d, bad_cfg, true, false).errors, "expected 4 fields for sdk mmwave_sdk_2, got 5"));
}

TEST_CASE(raw_capture_cfg_without_adcbufcfg_gives_notes_only) {
    // iwr_raw_rosnode cfgs (raw-capture firmware) have no adcbufCfg/lvdsStreamCfg
    BoardDescriptor d = must_load("IWR1443");
    CfgCheckResult r =
        check(d, std::string(CONFIG_DIR) + "/radar/DCA1000/iwr_raw_rosnode/14xx/indoor_human_rcs.cfg", true, false);
    CHECK(r.ok());
    CHECK_EQ(r.notes.size(), static_cast<size_t>(2));
}

TEST_CASE(rejects_dca1000_on_cascade) {
    BoardDescriptor d = must_load("AWR2243_CASCADE");
    std::string cfg = std::string(CONFIG_DIR) + "/radar/cascade/cascade_shortrange.cfg";
    CHECK(any_has(check(d, cfg, true, true).errors, "lvds.supported false"));
    CHECK(check(d, cfg, false, true).ok());
}

TEST_CASE(rejects_serial_with_unconfirmed_sdk2_dialect) {
    BoardDescriptor d = must_load("IWR1443");
    std::string cfg = write_cfg("bd_1443_serial.cfg", "adcCfg 2 1\nadcbufCfg 0 1 0 1\n");
    CHECK(any_has(check(d, cfg, false, true).errors, "design D7"));
}

TEST_CASE(rejects_adc_not_16_bit_and_missing_adccfg) {
    BoardDescriptor d = must_load("IWR1843");
    std::string cfg14 = write_cfg("bd_14bit.cfg",
                                  sdk3_cfg("adcCfg 1 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 1 0"));
    CHECK(any_has(check(d, cfg14, true, false).errors, "is not 16-bit"));
    std::string none = write_cfg("bd_noadc.cfg", sdk3_cfg("", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 1 0"));
    CHECK(any_has(check(d, none, true, false).errors, "no adcCfg line"));
}

TEST_CASE(rejects_schema_name_type_and_structure_errors) {
    CHECK(has(reject("IWR1843", [](json& j) { j["schema"] = 2; }), "unsupported schema 2"));
    CHECK(has(reject("IWR1843", [](json& j) { j["name"] = "IWR6843"; }), "must match the file name"));
    CHECK(has(reject("IWR1843", [](json& j) { j["bogus"] = 1; }), "/bogus: unknown key"));
    CHECK(has(reject("IWR1843", [](json& j) { j["data_uart"]["baud"] = "921600"; }), "expected an integer"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cli"].erase("ack"); }), "/cli/ack: missing required key"));
    CHECK(has(reject("IWR1843", [](json& j) { j["data_uart"]["tlv_dialect"] = "sdk4"; }), "not one of"));
    CHECK(has(reject("IWR1843", [](json& j) { j["sdk"] = "mmwave_sdk_4"; }), "/sdk"));
    CHECK(has(reject("IWR1843", [](json& j) { j["dca1000"]["packet_bytes"] = 1500; }), "outside [11, 1472]"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["rx_mask_fields"] = json::array({1, -4}); }),
              "/cfg_dialect/rx_mask_fields/1: must not be negative"));
    CHECK(has(reject("IWR1843", [](json& j) { j.erase("dca1000"); }), "required when lvds.supported"));
    CHECK(has(reject("AWR2243_CASCADE", [](json& j) { j["lvds"]["lanes"] = 4; }), "/lvds/lanes: unknown key"));
    CHECK(has(reject("AWR2243_CASCADE", [](json& j) { j["dca1000"] = json::object(); }), "not allowed"));
}

TEST_CASE(board_overrides_are_merged_then_validated) {
    BoardDescriptor d;
    std::string err;
    json ok = {{"data_uart", {{"timeout_ms", 2500}}}, {"cli", {{"cmd_timeout_ms", 300}}}};
    CHECK(BoardDescriptor::load_by_name(kBoards, "IWR1843", d, err, &ok));
    CHECK_EQ(d.data_uart.timeout_ms, 2500u);
    CHECK_EQ(d.cli.cmd_timeout_ms, 300u);
    CHECK_EQ(d.data_uart.baud, 921600u);  // untouched sibling kept

    json typo = {{"data_uart", {{"timeout", 2500}}}};
    CHECK(!BoardDescriptor::load_by_name(kBoards, "IWR1843", d, err, &typo));
    CHECK(has(err, "with board_overrides"));
    CHECK(has(err, "/data_uart/timeout: unknown key"));
}

TEST_CASE(rejects_bad_names_files_and_json) {
    BoardDescriptor d;
    std::string err;
    CHECK(!BoardDescriptor::load_by_name(kBoards, "../boards/IWR1843", d, err));
    CHECK(has(err, "plain name"));
    CHECK(!BoardDescriptor::load_by_name(kBoards, "IWR9999", d, err));
    CHECK(has(err, "cannot open"));
    std::string bad = std::string(TEST_TMP_DIR) + "/bd_broken.json";
    {
        std::ofstream f(bad);
        f << "{ \"schema\": 1, ";
    }
    CHECK(!BoardDescriptor::load(bad, d, err));
    CHECK(has(err, "not valid JSON"));
}

TEST_MAIN()
