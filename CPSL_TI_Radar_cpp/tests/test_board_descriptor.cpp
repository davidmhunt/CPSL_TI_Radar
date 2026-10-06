// BoardDescriptor: strict loading of config/boards/*.json and the radar .cfg
// cross-checks (driver v2 design §1, directive core-09).
//
// Required coverage: the four shipped boards load (4 cases) and six rejection
// cases (unknown key, bad enum, lanes/layout mismatch, and three cfg
// mismatches). Further cases after those pin the rest of the contract.
#include "test_harness.hpp"
#include "BoardDescriptor.hpp"

#include <fstream>
#include <iterator>
#include <sstream>
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
    CHECK_EQ(d.cli.prompt, std::string(":/>"));  // substring: matches mmwDemo:/> and mm_sar_lvds:/> (core-21)
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

TEST_CASE(serial_with_sdk2_dialect_is_accepted) {
    // core-16: the SDK 2 frame format is confirmed (docs/research/sdk2_uart_format_2026-10-05.md)
    BoardDescriptor d = must_load("IWR1443");
    std::string cfg = write_cfg("bd_1443_serial.cfg", "adcCfg 2 1\nadcbufCfg 0 1 0 1\n");
    CHECK(check(d, cfg, false, true).ok());
}

TEST_CASE(header_bytes_must_match_the_tlv_dialect) {
    CHECK(has(reject("IWR1843", [](json& j) { j["data_uart"]["header_bytes"] = 36; }),
              "/data_uart/header_bytes: must be 40 for tlv_dialect sdk3"));
    CHECK(has(reject("IWR1443", [](json& j) { j["data_uart"]["header_bytes"] = 40; }),
              "must be 36 for tlv_dialect sdk2"));
    CHECK(has(reject("IWR1843", [](json& j) { j["data_uart"]["tlv_dialect"] = "sdk2"; }),
              "must be 36 for tlv_dialect sdk2"));
    CHECK(has(reject("AWR2243_CASCADE", [](json& j) { j["data_uart"]["header_bytes"] = 32; }),
              "must be 40 for tlv_dialect mcuplus_cascade"));
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

TEST_CASE(stop_timeout_is_optional_null_means_computed) {
    for (const char* name : {"IWR1443", "IWR1843", "IWR6843", "AWR2243_CASCADE"}) {
        BoardDescriptor d = must_load(name);
        CHECK_EQ(d.cli.stop_timeout_ms, 0u);  // shipped files: null = computed
    }
    BoardDescriptor d;
    std::string err;
    json set = {{"cli", {{"stop_timeout_ms", 750}}}};
    CHECK(BoardDescriptor::load_by_name(kBoards, "IWR1843", d, err, &set));
    CHECK_EQ(d.cli.stop_timeout_ms, 750u);
    json omitted = {{"cli", {{"stop_timeout_ms", nullptr}}}};  // merge patch: null removes the key
    CHECK(BoardDescriptor::load_by_name(kBoards, "IWR1843", d, err, &omitted));
    CHECK_EQ(d.cli.stop_timeout_ms, 0u);
    CHECK(has(reject("IWR1843", [](json& j) { j["cli"]["stop_timeout_ms"] = 0; }),
              "/cli/stop_timeout_ms: 0 is outside [1, 600000]"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cli"]["stop_timeout_ms"] = "300"; }), "expected an integer"));
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

// ---------------------------------------------------------------------------
// Duplicate JSON keys (core-09 review F2): nlohmann keeps the last value, so
// the loader must reject them instead of silently using one.
// ---------------------------------------------------------------------------

static std::string load_text(const std::string& name, const std::string& text) {
    std::string path = std::string(TEST_TMP_DIR) + "/" + name;
    {
        std::ofstream f(path);
        f << text;
    }
    BoardDescriptor d;
    std::string err;
    if (BoardDescriptor::load(path, d, err)) return "";
    std::cout << "    rejected as expected: " << err << std::endl;
    return err;
}

// The shipped IWR1843 text with `needle` replaced by `repl` (first occurrence).
static std::string iwr1843_with(const std::string& needle, const std::string& repl) {
    std::ifstream f(kBoards + "/IWR1843.json");
    std::string s((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    std::string::size_type at = s.find(needle);
    CHECK(at != std::string::npos);
    if (at != std::string::npos) s.replace(at, needle.size(), repl);
    return s;
}

TEST_CASE(rejects_duplicate_key_top_level) {
    std::string e = load_text("IWR1843.json", iwr1843_with("\"sdk\": \"mmwave_sdk_3\",",
                                                           "\"sdk\": \"mmwave_sdk_3\", \"sdk\": \"mmwave_sdk_2\","));
    CHECK(has(e, "IWR1843.json: /sdk: duplicate key \"sdk\""));
}

TEST_CASE(rejects_duplicate_key_nested) {
    std::string e = load_text("IWR1843.json", iwr1843_with("\"baud\": 115200,", "\"baud\": 115200, \"baud\": 9600,"));
    CHECK(has(e, "/cli/baud: duplicate key \"baud\""));
}

TEST_CASE(rejects_duplicate_key_inside_array_element) {
    // the path names the array index; also check through parse_json_strict directly
    std::istringstream in("{\"a\": [1, {\"x\": 1}, {\"y\": 2, \"y\": 3}]}");
    json j;
    std::string err;
    CHECK(!cpsl::radar::parse_json_strict(in, "mem", j, err));
    CHECK_EQ(err, std::string("mem: /a/2/y: duplicate key \"y\" (each key may appear once per object)"));
}

TEST_CASE(same_key_in_different_objects_is_fine) {
    std::istringstream in("{\"a\": {\"k\": 1}, \"b\": {\"k\": 2}, \"c\": [{\"k\": 3}, {\"k\": 4}]}");
    json j;
    std::string err;
    CHECK(cpsl::radar::parse_json_strict(in, "mem", j, err));
    CHECK_EQ(j["c"][1]["k"].get<int>(), 4);
    // and all four shipped boards still load
    for (const char* b : {"IWR1443", "IWR1843", "IWR6843", "AWR2243_CASCADE"}) must_load(b);
}

// ---------------------------------------------------------------------------
// cfg_dialect.skip_commands and filter_cfg_commands (calibData rule)
// ---------------------------------------------------------------------------

using cpsl::radar::CfgCommandPlan;
using cpsl::radar::filter_cfg_commands;

static std::vector<std::string> v(std::initializer_list<const char*> l) {
    std::vector<std::string> out;
    for (const char* s : l) out.push_back(s);
    return out;
}

TEST_CASE(skip_commands_per_board) {
    // IWR1843 only: its flashed firmware answers "'calibData' is not recognized"
    // (every core-04 baseline run). The others have no evidence, so no entry.
    CHECK(must_load("IWR1843").cfg_dialect.skip_commands == v({"calibData"}));
    CHECK(must_load("IWR6843").cfg_dialect.skip_commands.empty());
    CHECK(must_load("IWR1443").cfg_dialect.skip_commands.empty());
    CHECK(must_load("AWR2243_CASCADE").cfg_dialect.skip_commands.empty());
}

TEST_CASE(skip_commands_validation) {
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = "calibData"; }),
              "/cfg_dialect/skip_commands: expected an array"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array({"calib Data"}); }),
              "/cfg_dialect/skip_commands/0: \"calib Data\" must be one command word"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array({""}); }),
              "must be one command word"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array({1}); }),
              "/cfg_dialect/skip_commands/0: expected a string"));
    CHECK(has(reject("IWR1843",
                     [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array({"calibData", "calibData"}); }),
              "listed twice"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array({"sensorStart"}); }),
              "cannot be skipped"));
    // an empty list is valid, and board_overrides can clear the shipped list
    CHECK_EQ(reject("IWR1843", [](json& j) { j["cfg_dialect"]["skip_commands"] = json::array(); }), std::string(""));
    BoardDescriptor d;
    std::string err;
    json clear = {{"cfg_dialect", {{"skip_commands", json::array()}}}};
    CHECK(BoardDescriptor::load_by_name(kBoards, "IWR1843", d, err, &clear));
    CHECK(d.cfg_dialect.skip_commands.empty());
}

TEST_CASE(filter_skips_listed_command) {
    BoardDescriptor d = must_load("IWR1843");
    CfgCommandPlan p = filter_cfg_commands(v({"sensorStop", "flushCfg", "calibData 0 0 0", "sensorStart"}), d);
    CHECK(p.send == v({"sensorStop", "flushCfg"}));
    CHECK(p.skipped == v({"calibData 0 0 0"}));
}

TEST_CASE(filter_matches_first_token_exactly_ignoring_whitespace) {
    BoardDescriptor d = must_load("IWR1843");
    CfgCommandPlan p = filter_cfg_commands(
        v({"calibData 0 0 0\r", "  calibData\t0 0 0  ", "calibData", "calibdata 0 0 0", "CALIBDATA 0 0 0",
           "calibDataX 0", "xcalibData 0", "% calibData 0 0 0", "#calibData"}),
        d);
    // leading/trailing whitespace and tabs do not hide the command
    CHECK(p.skipped == v({"calibData 0 0 0", "  calibData\t0 0 0", "calibData"}));
    // other spellings are sent (and rejected by the firmware, as before); comments dropped
    CHECK(p.send == v({"calibdata 0 0 0", "CALIBDATA 0 0 0", "calibDataX 0", "xcalibData 0"}));
}

TEST_CASE(filter_keeps_other_commands_in_order) {
    BoardDescriptor d = must_load("IWR1843");
    std::vector<std::string> in = v({"% comment", "", "sensorStop", "flushCfg", "dfeDataOutputMode 1",
                                     "channelCfg 15 7 0", "calibData 0 0 0", "adcCfg 2 1",
                                     "  lvdsStreamCfg -1 0 1 0", "sensorStart", "\r"});
    CfgCommandPlan p = filter_cfg_commands(in, d);
    CHECK(p.send == v({"sensorStop", "flushCfg", "dfeDataOutputMode 1", "channelCfg 15 7 0", "adcCfg 2 1",
                       "  lvdsStreamCfg -1 0 1 0"}));
    CHECK_EQ(p.skipped.size(), static_cast<size_t>(1));
}

TEST_CASE(filter_with_empty_skip_list_is_a_no_op) {
    BoardDescriptor d = must_load("IWR6843");
    CHECK(d.cfg_dialect.skip_commands.empty());
    std::vector<std::string> in = v({"sensorStop", "calibData 0 0 0", "frameCfg 0 1 16 0 100 1 0", "sensorStart"});
    CfgCommandPlan p = filter_cfg_commands(in, d);
    CHECK(p.send == v({"sensorStop", "calibData 0 0 0", "frameCfg 0 1 16 0 100 1 0"}));
    CHECK(p.skipped.empty());
}

// cfg_dialect.required_commands / forbidden_commands and data_uart.supported (core-22 Step 1)
TEST_CASE(shipped_boards_are_unchanged_by_the_new_keys) {
    for (const char* n : {"IWR1443", "IWR1843", "IWR6843", "AWR2243_CASCADE"}) {
        BoardDescriptor d = must_load(n);
        CHECK(d.cfg_dialect.required_commands.empty());
        CHECK(d.cfg_dialect.forbidden_commands.empty());
        CHECK(d.data_uart.supported);
        CHECK(d.data_uart.baud > 0);
        CHECK(d.data_uart.header_bytes == 36 || d.data_uart.header_bytes == 40);
    }
    // golden values that the new keys must not disturb
    BoardDescriptor b = must_load("IWR1843");
    CHECK(b.cfg_dialect.skip_commands == v({"calibData"}));
    CHECK_EQ(b.data_uart.header_bytes, 40u);
    CHECK_EQ(b.lvds.lanes, 2u);
}

TEST_CASE(required_forbidden_validation) {
    for (const char* key : {"required_commands", "forbidden_commands"}) {
        const std::string base = std::string("/cfg_dialect/") + key;
        CHECK(has(reject("IWR1843", [&](json& j) { j["cfg_dialect"][key] = "x"; }), base + ": expected an array"));
        CHECK(has(reject("IWR1843", [&](json& j) { j["cfg_dialect"][key] = json::array({"a b"}); }),
                  base + "/0: \"a b\" must be one command word"));
        CHECK(has(reject("IWR1843", [&](json& j) { j["cfg_dialect"][key] = json::array({"x", "x"}); }),
                  "listed twice"));
        CHECK(has(reject("IWR1843", [&](json& j) { j["cfg_dialect"][key] = json::array({2}); }),
                  base + "/0: expected a string"));
        CHECK_EQ(reject("IWR1843", [&](json& j) { j["cfg_dialect"][key] = json::array(); }), std::string(""));
    }
    CHECK(has(reject("IWR1843",
                     [](json& j) {
                         j["cfg_dialect"]["required_commands"] = json::array({"foo"});
                         j["cfg_dialect"]["forbidden_commands"] = json::array({"foo"});
                     }),
              "also in forbidden_commands"));
    CHECK(has(reject("IWR1843", [](json& j) { j["cfg_dialect"]["required_commands"] = json::array({"calibData"}); }),
              "also in skip_commands"));
}

static BoardDescriptor with_dialect(const json& overrides) {
    json j = read_json(kBoards + "/IWR1843.json");
    j.merge_patch(overrides);
    BoardDescriptor d;
    std::string err;
    bool ok = BoardDescriptor::from_json(j, "IWR1843", "test:dialect", d, err);
    if (!ok) std::cerr << "load failed: " << err << std::endl;
    CHECK(ok);
    return d;
}

TEST_CASE(cross_check_enforces_required_and_forbidden_commands) {
    BoardDescriptor d = with_dialect(json{{"cfg_dialect", {{"skip_commands", json::array()},
                                                           {"required_commands", json::array({"calibData"})},
                                                           {"forbidden_commands", json::array({"guiMonitor"})}}}});
    const std::string good = sdk3_cfg("adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 1 0");
    CHECK_EQ(check(d, write_cfg("rf_missing.cfg", good), true, false).errors.size(), size_t(1));
    CfgCheckResult m = check(d, write_cfg("rf_missing2.cfg", good), true, false);
    CHECK(any_has(m.errors, "required command calibData is missing"));
    CHECK(any_has(m.errors, "IWR1843"));
    CHECK(check(d, write_cfg("rf_ok.cfg", good + "\ncalibData 0 0 0\n"), true, false).ok());
    CfgCheckResult f = check(d, write_cfg("rf_forbid.cfg", good + "\ncalibData 0 0 0\nguiMonitor -1 1 0 0 0 0 0\n"),
                             true, false);
    CHECK(any_has(f.errors, "command guiMonitor is forbidden for board IWR1843"));
    CHECK(any_has(f.errors, "line "));
    // commented-out lines do not count either way
    CHECK(check(d, write_cfg("rf_comment.cfg", good + "\ncalibData 0 0 0\n% guiMonitor 1\n"), true, false).ok());
    // enforced even when only the serial stream is selected
    CHECK(!check(d, write_cfg("rf_serial.cfg", good + "\ncalibData 0 0 0\nguiMonitor 1\n"), false, true).ok());
}

TEST_CASE(data_uart_unsupported_board) {
    // tlv_dialect / header_bytes etc. not required
    json j = read_json(kBoards + "/IWR1843.json");
    j["data_uart"] = json{{"supported", false}};
    BoardDescriptor d;
    std::string err;
    CHECK(BoardDescriptor::from_json(j, "IWR1843", "test:nouart", d, err));
    CHECK(!d.data_uart.supported);
    // ... and extra data_uart keys are then unknown
    CHECK(has(reject("IWR1843", [](json& jj) { jj["data_uart"]["supported"] = false; }), "unknown key"));
    // supported:true spelled out is the default and loads with the full block
    CHECK_EQ(reject("IWR1843", [](json& jj) { jj["data_uart"]["supported"] = true; }), std::string(""));
    CHECK(has(reject("IWR1843", [](json& jj) { jj["data_uart"]["supported"] = "no"; }), "/data_uart/supported"));
    // serial_stream on such a board is an error; DCA-only is fine
    const std::string cfg = write_cfg("nouart.cfg", sdk3_cfg("adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 0 1 0"));
    CfgCheckResult r = check(d, cfg, false, true);
    CHECK(any_has(r.errors, "data_uart.supported false"));
    CHECK(check(d, cfg, true, false).ok());
}

TEST_MAIN()

// ---------------------------------------------------------------------------
// IWR1843_SAR descriptor (core-22 Step 3/4)
// ---------------------------------------------------------------------------

static const std::string kSarCfg = std::string(CONFIG_DIR) + "/radar/sar_configs/1843_SAR_2ms_fmt1.cfg";

static std::string read_text(const std::string& path) {
    std::ifstream f(path);
    return std::string(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
}

TEST_CASE(sar_descriptor_differs_from_iwr1843_only_as_intended) {
    json sar = read_json(kBoards + "/IWR1843_SAR.json");
    json base = read_json(kBoards + "/IWR1843.json");
    CHECK_EQ(sar["name"].get<std::string>(), std::string("IWR1843_SAR"));
    // apply the intended differences to the stock descriptor: the rest must be identical
    base["name"] = "IWR1843_SAR";
    base["cli"]["stop_timeout_ms"] = 4000;
    base["cfg_dialect"]["skip_commands"] = json::array();
    base["cfg_dialect"]["required_commands"] = sar["cfg_dialect"]["required_commands"];
    base["cfg_dialect"]["forbidden_commands"] = sar["cfg_dialect"]["forbidden_commands"];
    base["data_uart"] = json{{"supported", false}};
    CHECK(base == sar);

    BoardDescriptor d = must_load("IWR1843_SAR");
    CHECK(d.cfg_dialect.skip_commands.empty());  // calibData is sent
    CHECK(d.cfg_dialect.required_commands == v({"adcbufCfg", "lvdsStreamCfg", "analogMonitor", "calibData"}));
    CHECK_EQ(d.cfg_dialect.forbidden_commands.size(), size_t(11));
    CHECK(!d.data_uart.supported);
    CHECK(d.lvds.supported);
    CHECK(d.lvds.iq_order == must_load("IWR1843").lvds.iq_order);
    std::vector<std::string> lines;
    {
        std::istringstream in(read_text(kSarCfg));
        for (std::string line; std::getline(in, line);)
            if (!line.empty() && line[0] != '%') lines.push_back(line);
    }
    CfgCommandPlan p = filter_cfg_commands(lines, d);
    bool calib = false;
    for (const auto& c : p.send) calib = calib || c.rfind("calibData", 0) == 0;
    CHECK(calib);
    CHECK(p.skipped.empty());
}

TEST_CASE(sar_cross_check_accepts_sar_cfg_and_rejects_others) {
    BoardDescriptor d = must_load("IWR1843_SAR");
    CfgCheckResult ok = check(d, kSarCfg, true, false);
    CHECK(ok.ok());
    const std::string text = read_text(kSarCfg);
    // stock-style cfg: forbidden commands
    CfgCheckResult f = check(d, write_cfg("sar_stock.cfg", text + "guiMonitor -1 1 1 0 0 0 1\ncfarCfg -1 0 2 8 4 3 0 15 1\n"), true, false);
    CHECK(any_has(f.errors, "command guiMonitor is forbidden for board IWR1843_SAR"));
    CHECK(any_has(f.errors, "command cfarCfg is forbidden"));
    // missing calibData
    std::string nocal;
    std::istringstream in(text);
    for (std::string line; std::getline(in, line);)
        if (line.rfind("calibData", 0) != 0) nocal += line + "\n";
    CHECK(any_has(check(d, write_cfg("sar_nocal.cfg", nocal), true, false).errors, "required command calibData is missing"));
    // dataFmt 2 (core-24)
    std::string fmt2 = text;
    const std::string a = "lvdsStreamCfg -1 0 1 0";
    fmt2.replace(fmt2.find(a), a.size(), "lvdsStreamCfg -1 1 2 0");
    CHECK(!check(d, write_cfg("sar_fmt2.cfg", fmt2), true, false).ok());
    // serial stream on this board is refused
    CHECK(!check(d, kSarCfg, false, true).ok());
    CHECK(!check(d, kSarCfg, true, true).ok());
}
