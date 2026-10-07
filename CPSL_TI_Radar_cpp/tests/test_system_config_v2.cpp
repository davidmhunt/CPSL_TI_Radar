// SystemConfigReader, schema v2 (driver v2 design §2, directive core-10):
// parsing, defaults, board_overrides, optional sections, the v1 migration
// message, type/range/unknown-key rejection and the radar .cfg cross-check.
#include "test_harness.hpp"
#include "SystemConfigReader.hpp"

#include <cstdlib>
#include <fstream>
#include <sys/stat.h>

static const std::string kTmp = TEST_TMP_DIR;
static const std::string kData = TEST_DATA_DIR;
static const std::string kBoards = std::string(CONFIG_DIR) + "/boards";

// Configs here live in the build tree, so point the board lookup at the
// shipped descriptors (the <json dir>/../boards rule has its own case).
static const bool kEnvSet = [] {
    setenv(SystemConfigReader::kBoardsDirEnv, kBoards.c_str(), 1);
    return true;
}();

// A complete, valid v2 config (IWR1843, DCA1000 streaming, everything explicit).
static json base_config() {
    json j = json::parse(R"({
        "schema_version": 2,
        "board": "IWR1843",
        "board_overrides": {},
        "radar_cfg": "",
        "cli": { "port": "/dev/ttyACM0" },
        "serial_stream": { "enabled": false, "port": "/dev/ttyACM1" },
        "dca1000": { "enabled": true, "fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30",
                     "cmd_port": 4096, "data_port": 4098, "rcvbuf_bytes": 33554432 },
        "output": { "dir": "out/front", "save_adc_frames": true, "save_raw_lvds": false },
        "runtime": { "log_level": "debug", "frame_queue_depth": 4, "stall_timeout_ms": 0,
                     "rx_cpu": null, "worker_cpu": 2, "rx_priority": 99, "worker_priority": 80 }
    })");
    j["radar_cfg"] = kData + "/radar/iwr1843.cfg";
    return j;
}

static std::string write_text(const std::string& name, const std::string& text) {
    std::string path = kTmp + "/" + name;
    std::ofstream f(path);
    f << text;
    return path;
}

static std::string write_json(const std::string& name, const json& j) { return write_text(name, j.dump(4)); }

static bool has(const std::string& s, const std::string& sub) { return s.find(sub) != std::string::npos; }

// Load `j` and expect failure; returns the error.
static std::string reject(const std::string& name, const json& j) {
    SystemConfigReader r(write_json(name, j));
    CHECK(!r.initialized);
    std::cout << "    rejected as expected: " << r.get_error() << std::endl;
    return r.get_error();
}

TEST_CASE(full_v2_config_fields) {
    const std::string path = write_json("v2_full.json", base_config());
    SystemConfigReader r(path);
    CHECK(r.initialized);
    CHECK_EQ(r.getBoard().name, std::string("IWR1843"));
    CHECK_EQ(r.getBoardPath(), kBoards + "/IWR1843.json");
    CHECK_EQ(r.getRadarConfigPath(), kData + "/radar/iwr1843.cfg");
    CHECK_EQ(r.getRadarCliPort(), std::string("/dev/ttyACM0"));
    CHECK_EQ(r.getRadarDataPort(), std::string("/dev/ttyACM1"));
    CHECK(!r.get_serial_streaming_enabled());
    CHECK(r.get_dca1000_streaming_enabled());
    CHECK_EQ(r.getDCAFpgaIP(), std::string("192.168.33.180"));
    CHECK_EQ(r.getDCASystemIP(), std::string("192.168.33.30"));
    CHECK_EQ(r.getDCACmdPort(), 4096);
    CHECK_EQ(r.getDCADataPort(), 4098);
    CHECK_EQ(r.getDCARcvbufBytes(), static_cast<size_t>(33554432));
    CHECK_EQ(r.get_output_dir(), kTmp + "/out/front");  // relative to the JSON file
    CHECK_EQ(r.get_output_path("adc_data.bin"), kTmp + "/out/front/adc_data.bin");
    CHECK(r.get_save_adc_frames());
    CHECK(!r.get_save_raw_lvds());
    CHECK(r.get_log_level() == LogLevel::debug);
    CHECK(r.get_verbose());
    CHECK_EQ(r.get_frame_queue_depth(), 4u);
    CHECK_EQ(r.get_rx_cpu(), -1);
    CHECK_EQ(r.get_worker_cpu(), 2);
    CHECK_EQ(r.get_rx_priority(), 99u);
    CHECK_EQ(r.get_worker_priority(), 80u);
    // CLI and UART settings come from the board descriptor
    CHECK_EQ(r.getRadarCliBaudRate(), 115200u);
    CHECK_EQ(r.getRadarCliTimeoutMs(), 100);
    CHECK_EQ(r.getRadarDataBaudRate(), 921600u);
    CHECK_EQ(r.getRadarDataTimeoutMs(), 1000);
    // iwr1843.cfg has no adcbufCfg: a cross-check note, not an error
    CHECK_EQ(r.getCfgCheckNotes().size(), static_cast<size_t>(1));
}

TEST_CASE(minimal_config_defaults_and_optional_sections) {
    // disabled stream sections, output and runtime may all be omitted
    json j = {{"schema_version", 2},
              {"board", "IWR1843"},
              {"radar_cfg", kData + "/radar/iwr1843.cfg"},
              {"cli", {{"port", "/dev/ttyACM0"}}},
              {"serial_stream", {{"enabled", true}, {"port", "/dev/ttyACM1"}}}};
    SystemConfigReader r(write_json("v2_min.json", j));
    CHECK(r.initialized);
    CHECK(r.get_serial_streaming_enabled());
    CHECK(!r.get_dca1000_streaming_enabled());
    CHECK_EQ(r.get_output_dir(), std::string(""));  // current directory, as in v1
    CHECK_EQ(r.get_output_path("adc_data.bin"), std::string("adc_data.bin"));
    CHECK(!r.get_save_adc_frames());
    CHECK(!r.get_save_raw_lvds());
    CHECK(r.get_log_level() == LogLevel::info);
    CHECK(!r.get_verbose());
    CHECK_EQ(r.getDCARcvbufBytes(), static_cast<size_t>(64u * 1024u * 1024u));
    CHECK_EQ(r.get_frame_queue_depth(), 4u);
    CHECK_EQ(r.get_stall_timeout_ms(), 0u);
    CHECK_EQ(r.get_rx_cpu(), -1);
    CHECK_EQ(r.get_worker_cpu(), -1);
    CHECK_EQ(r.get_rx_priority(), 0u);      // SCHED_RR is opt-in (core-20)
    CHECK_EQ(r.get_worker_priority(), 0u);

    // a disabled section may omit everything but "enabled"
    json k = j;
    k["dca1000"] = {{"enabled", false}};
    CHECK(SystemConfigReader(write_json("v2_min_dca_off.json", k)).initialized);
}

TEST_CASE(board_overrides_merge_over_descriptor) {
    json j = base_config();
    j["board_overrides"] = {{"cli", {{"cmd_timeout_ms", 250}}},
                            {"data_uart", {{"baud", 460800}, {"timeout_ms", 2500}}},
                            {"cfg_dialect", {{"skip_commands", json::array()}}}};
    SystemConfigReader r(write_json("v2_overrides.json", j));
    CHECK(r.initialized);
    CHECK_EQ(r.getRadarCliTimeoutMs(), 250);
    CHECK_EQ(r.getRadarCliBaudRate(), 115200u);  // untouched sibling from the descriptor
    CHECK_EQ(r.getRadarDataBaudRate(), 460800u);
    CHECK_EQ(r.getRadarDataTimeoutMs(), 2500);
    CHECK(r.getBoard().cfg_dialect.skip_commands.empty());

    // an override is validated like the descriptor itself
    json bad = base_config();
    bad["board_overrides"] = {{"cli", {{"bauds", 9600}}}};
    std::string e = reject("v2_override_typo.json", bad);
    CHECK(has(e, "with board_overrides"));
    CHECK(has(e, "/cli/bauds: unknown key"));
    bad["board_overrides"] = json::array();
    CHECK(has(reject("v2_override_array.json", bad), "/board_overrides: expected an object"));
}

TEST_CASE(v1_file_names_the_migration_script) {
    json v1 = json::parse(R"({
        "verbose": false,
        "TI_Radar_Config_Management": { "TI_Radar_config_path": "x.cfg" },
        "CLI_Controller": { "CLI_port": "/dev/ttyACM0" },
        "Streamer": { "board_type": "IWR1843" }
    })");
    std::string e = reject("v1.json", v1);
    CHECK(has(e, "v1 system config"));
    CHECK(has(e, "uv run tools/migrate_config_v1_to_v2.py"));

    json j = base_config();
    j["schema_version"] = 3;
    CHECK(has(reject("v2_schema3.json", j), "unsupported schema_version 3"));
    j["schema_version"] = "2";
    CHECK(has(reject("v2_schema_str.json", j), "unsupported schema_version \"2\""));
}

TEST_CASE(unknown_keys_rejected_everywhere) {
    const char* const sections[] = {"cli", "serial_stream", "dca1000", "output", "runtime"};
    for (const char* s : sections) {
        json j = base_config();
        j[s]["bogus"] = 1;
        std::string e = reject(std::string("v2_unknown_") + s + ".json", j);
        CHECK(has(e, std::string("/") + s + "/bogus: unknown key"));
    }
    json j = base_config();
    j["verbose"] = true;  // a v1 key mixed into a v2 file
    CHECK(has(reject("v2_unknown_top.json", j), "/verbose: unknown key"));
}

TEST_CASE(bad_types_and_ranges_rejected) {
    struct Case {
        const char* ptr;
        json value;
        const char* expect;
    };
    const Case cases[] = {
        {"/board", 1843, "/board: expected a string"},
        {"/radar_cfg", "", "/radar_cfg: must not be empty"},
        {"/cli/port", false, "/cli/port: expected a string"},
        {"/dca1000/enabled", "yes", "/dca1000/enabled: expected true or false"},
        {"/dca1000/cmd_port", 70000, "/dca1000/cmd_port: 70000 is outside [1, 65535]"},
        {"/dca1000/data_port", -1, "/dca1000/data_port: must not be negative"},
        {"/dca1000/rcvbuf_bytes", 0, "/dca1000/rcvbuf_bytes: 0 is outside"},
        {"/output/save_adc_frames", 1, "/output/save_adc_frames: expected true or false"},
        {"/output/dir", "", "/output/dir: must not be empty"},
        {"/runtime/log_level", "verbose", "\"verbose\" is not one of: error, warn, info, debug"},
        {"/runtime/frame_queue_depth", 0, "/runtime/frame_queue_depth: 0 is outside [1, 1024]"},
        {"/runtime/rx_cpu", "0", "/runtime/rx_cpu: expected an integer"},
        {"/runtime/rx_priority", 100, "/runtime/rx_priority: 100 is outside [0, 99]"},
        {"/runtime/stall_timeout_ms", 1.5, "/runtime/stall_timeout_ms: expected an integer"},
    };
    int i = 0;
    for (const Case& c : cases) {
        json j = base_config();
        j[json::json_pointer(c.ptr)] = c.value;
        std::string e = reject("v2_bad_" + std::to_string(i++) + ".json", j);
        CHECK(has(e, c.expect));
    }
}

TEST_CASE(explicit_zero_priority_is_accepted) {
    json j = base_config();
    j["runtime"]["rx_priority"] = 0;
    j["runtime"]["worker_priority"] = 0;
    SystemConfigReader r(write_json("v2_prio0.json", j));
    CHECK(r.initialized);
    CHECK_EQ(r.get_rx_priority(), 0u);
    CHECK_EQ(r.get_worker_priority(), 0u);
}

TEST_CASE(required_keys_and_enabled_streams) {
    for (const char* k : {"board", "radar_cfg", "cli"}) {
        json j = base_config();
        j.erase(k);
        CHECK(has(reject(std::string("v2_missing_") + k + ".json", j), std::string("/") + k + ": missing required key"));
    }
    json j = base_config();
    j["dca1000"].erase("fpga_ip");
    CHECK(has(reject("v2_dca_no_ip.json", j), "/dca1000/fpga_ip: required when dca1000.enabled is true"));
    j = base_config();
    j["serial_stream"] = {{"enabled", true}};
    CHECK(has(reject("v2_serial_no_port.json", j), "/serial_stream/port: required when"));
    j = base_config();
    j["dca1000"]["enabled"] = false;
    CHECK(has(reject("v2_nothing_enabled.json", j), "nothing to stream"));
}

TEST_CASE(duplicate_keys_rejected) {
    std::string text = base_config().dump(4);
    text.replace(text.find("\"cli\""), 5, "\"cli\": {\"port\": \"/dev/x\"}, \"cli\"");
    SystemConfigReader r(write_text("v2_dup.json", text));
    CHECK(!r.initialized);
    CHECK(has(r.get_error(), "/cli: duplicate key \"cli\""));
}

TEST_CASE(board_lookup_by_name_path_and_json_dir) {
    // a path (relative to the JSON file) instead of a name
    json j = base_config();
    j["board"] = std::string(CONFIG_DIR) + "/boards/IWR6843.json";
    SystemConfigReader byPath(write_json("v2_board_path.json", j));
    CHECK(byPath.initialized);
    CHECK_EQ(byPath.getBoard().name, std::string("IWR6843"));

    j["board"] = "IWR9999";
    std::string e = reject("v2_board_unknown.json", j);
    CHECK(has(e, "no descriptor \"IWR9999\""));
    CHECK(has(e, SystemConfigReader::kBoardsDirEnv));

    // without the environment variable: <json dir>/../boards, the config/ layout
    const std::string root = kTmp + "/v2_layout";
    mkdir(root.c_str(), 0755);
    mkdir((root + "/system").c_str(), 0755);
    mkdir((root + "/boards").c_str(), 0755);
    {
        std::ifstream in(kBoards + "/IWR1843.json");
        std::ofstream out(root + "/boards/IWR1843.json");
        out << in.rdbuf();
    }
    std::ofstream(root + "/system/s.json") << base_config().dump(4);
    unsetenv(SystemConfigReader::kBoardsDirEnv);
    SystemConfigReader byDir(root + "/system/s.json");
    setenv(SystemConfigReader::kBoardsDirEnv, kBoards.c_str(), 1);
    CHECK(byDir.initialized);
    CHECK_EQ(byDir.getBoardPath(), root + "/system/../boards/IWR1843.json");
}

TEST_CASE(relative_radar_cfg_and_missing_file) {
    json j = base_config();
    j["radar_cfg"] = "../data/radar/does_not_exist.cfg";
    std::string e = reject("v2_nocfg.json", j);
    CHECK(has(e, kTmp + "/../data/radar/does_not_exist.cfg: cannot open radar cfg"));
    SystemConfigReader missing(kTmp + "/no_such_config.json");
    CHECK(!missing.initialized);
    CHECK(has(missing.get_error(), "cannot open system config"));
    CHECK(has(reject("v2_notjson.json", json()), "expected a JSON object"));
}

TEST_CASE(cross_check_errors_fail_the_load) {
    // DCA1000 on the cascade (lvds.supported false)
    json j = base_config();
    j["board"] = "AWR2243_CASCADE";
    j["radar_cfg"] = kData + "/radar/awr2243_cascade.cfg";
    std::string e = reject("v2_cascade_dca.json", j);
    CHECK(has(e, "radar cfg does not fit board AWR2243_CASCADE"));
    CHECK(has(e, "lvds.supported false"));

    // serial on the IWR1443 is accepted since core-16 (sdk2 dialect confirmed)
    j = base_config();
    j["board"] = "IWR1443";
    j["radar_cfg"] = kData + "/radar/iwr1443.cfg";
    j["dca1000"]["enabled"] = false;
    j["serial_stream"]["enabled"] = true;
    SystemConfigReader r(write_json("v2_1443_serial.json", j));
    CHECK(r.initialized);
    CHECK(r.get_error().empty());
}

TEST_CASE(malformed_json_is_an_error_not_an_exception) {
    // core-02 characterized nlohmann::parse_error escaping; core-10's strict
    // parser returns it as a load error, pinned here for core-11
    const char* bad[] = {"{ \"schema_version\": 2, ", "not json", "", "{\"schema_version\": 2,}"};
    int k = 0;
    for (const char* text : bad) {
        SystemConfigReader r;
        bool threw = false;
        try {
            r.initialize(write_text("malformed_" + std::to_string(k++) + ".json", text));
        } catch (...) {
            threw = true;
        }
        CHECK(!threw);
        CHECK(!r.initialized);
        CHECK(!r.get_error().empty());
    }
}

TEST_CASE(copy_keeps_state) {
    SystemConfigReader a(write_json("v2_copy.json", base_config()));
    SystemConfigReader b(a);
    CHECK(b.initialized);
    CHECK_EQ(b.getBoard().name, std::string("IWR1843"));
    SystemConfigReader c;
    CHECK(!c.initialized);
    c = a;
    CHECK(c.initialized);
    CHECK_EQ(c.getRadarConfigPath(), a.getRadarConfigPath());
}

// ---- "firmware" key (gui-04 Step 1: optional, checked against the board list and the SAR alias) ----

static std::string reject_code(const std::string& name, const json& j, const std::string& code) {
    SystemConfigReader r(write_json(name, j));
    CHECK(!r.initialized);
    std::cout << "    rejected as expected: " << r.get_error() << std::endl;
    CHECK(!r.getIssues().empty());
    if (!r.getIssues().empty()) CHECK_EQ(r.getIssues()[0].code, code);
    return r.get_error();
}

TEST_CASE(firmware_key_optional_and_accepted) {
    json j = base_config();
    SystemConfigReader none(write_json("fw_none.json", j));
    CHECK(none.initialized);
    CHECK_EQ(none.getFirmwareId(), std::string(""));
    CHECK(none.getIssues().empty());

    // IWR1843 lists demo and iwr1843_sar_lvds; demo has an lvds output on the 1843
    j["firmware"] = "demo";
    SystemConfigReader demo(write_json("fw_demo.json", j));
    CHECK(demo.initialized);
    CHECK_EQ(demo.getFirmwareId(), std::string("demo"));
    CHECK_EQ(demo.getFirmware().id, std::string("demo"));
    CHECK(demo.getFirmware().supports_board("IWR1843"));

    // the SAR pair: board IWR1843_SAR + firmware iwr1843_sar_lvds (driver_board IWR1843 -> IWR1843_SAR)
    j["board"] = "IWR1843_SAR";
    j["firmware"] = "iwr1843_sar_lvds";
    j["radar_cfg"] = std::string(CONFIG_DIR) + "/radar/sar_configs/1843_SAR_2ms_fmt1.cfg";
    SystemConfigReader sar(write_json("fw_sar.json", j));
    CHECK(sar.initialized);
    if (!sar.initialized) std::cout << sar.get_error() << std::endl;
}

TEST_CASE(firmware_must_be_in_the_boards_list) {
    json j = base_config();
    j["firmware"] = "cascade_ddm";  // exists, but IWR1843 does not list it
    std::string e = reject_code("fw_not_listed.json", j, "firmware_unsupported");
    CHECK(has(e, "/firmware"));
    CHECK(has(e, "not supported by board IWR1843"));
    CHECK(has(e, "supports: demo, iwr1843_sar_lvds"));

    j["firmware"] = "nope";
    CHECK(has(reject_code("fw_unknown.json", j, "firmware_unsupported"), "supports: demo, iwr1843_sar_lvds"));

    j["firmware"] = "";
    CHECK(has(reject("fw_empty.json", j), "must not be empty"));
    j["firmware"] = 3;
    CHECK(has(reject("fw_int.json", j), "expected a string"));
}

TEST_CASE(sar_firmware_on_the_wrong_board_names_the_alias) {
    json j = base_config();
    j["firmware"] = "iwr1843_sar_lvds";  // board IWR1843 lists it, but it runs as IWR1843_SAR
    std::string e = reject_code("fw_alias.json", j, "firmware_alias");
    CHECK(has(e, "firmware iwr1843_sar_lvds on IWR1843 runs with board IWR1843_SAR"));
    CHECK(has(e, "set \"board\": \"IWR1843_SAR\""));

    // the reverse: the SAR board does not list demo
    j = base_config();
    j["board"] = "IWR1843_SAR";
    j["firmware"] = "demo";
    j["radar_cfg"] = std::string(CONFIG_DIR) + "/radar/sar_configs/1843_SAR_2ms_fmt1.cfg";
    CHECK(has(reject_code("fw_sar_demo.json", j, "firmware_unsupported"), "supports: iwr1843_sar_lvds"));
}

TEST_CASE(firmware_outputs_must_cover_the_enabled_streams) {
    // dca1000_raw is listed by IWR1443; serial_stream on a firmware whose tlv output is false is refused
    // by the board first (SAR), so check the descriptor rule with a descriptor dir that flips tlv off
    const std::string dir = kTmp + "/fwdir";
    mkdir(dir.c_str(), 0755);
    json fw;
    {
        std::ifstream f(std::string(CONFIG_DIR) + "/firmware/demo.json");
        fw = json::parse(f);
    }
    fw["outputs"]["IWR1843"]["tlv"] = false;
    fw["outputs"]["IWR1843"]["lvds"] = false;
    write_text("fwdir/demo.json", fw.dump(2));
    setenv(SystemConfigReader::kFirmwareDirEnv, dir.c_str(), 1);
    json j = base_config();
    j["firmware"] = "demo";
    CHECK(has(reject_code("fw_no_lvds.json", j, "firmware_output_lvds"), "has no LVDS output on IWR1843"));
    j["dca1000"]["enabled"] = false;
    j["serial_stream"]["enabled"] = true;
    CHECK(has(reject_code("fw_no_tlv.json", j, "firmware_output_tlv"), "has no TLV output on IWR1843"));
    unsetenv(SystemConfigReader::kFirmwareDirEnv);

    // a malformed descriptor is reported as such, with the descriptor as source
    write_text("fwdir/demo.json", "{ \"schema\": 2 }");
    setenv(SystemConfigReader::kFirmwareDirEnv, dir.c_str(), 1);
    j = base_config();
    j["firmware"] = "demo";
    SystemConfigReader bad(write_json("fw_bad_desc.json", j));
    CHECK(!bad.initialized);
    CHECK(!bad.getIssues().empty());
    if (!bad.getIssues().empty()) {
        CHECK_EQ(bad.getIssues()[0].code, std::string("firmware_descriptor"));
        CHECK(has(bad.getIssues()[0].source, "fwdir/demo.json"));
    }
    unsetenv(SystemConfigReader::kFirmwareDirEnv);
}

TEST_CASE(cross_check_errors_become_one_issue_each) {
    json j = base_config();
    j["board"] = "AWR2243_CASCADE";
    j["radar_cfg"] = kData + "/radar/awr2243_cascade.cfg";
    SystemConfigReader r(write_json("issues_cascade_dca.json", j));
    CHECK(!r.initialized);
    CHECK(!r.getIssues().empty());
    for (const auto& i : r.getIssues()) CHECK_EQ(i.code, std::string("radar_cfg"));
}

TEST_MAIN()
