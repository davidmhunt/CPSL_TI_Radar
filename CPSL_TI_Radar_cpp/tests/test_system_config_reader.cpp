// SystemConfigReader: JSON system-config parsing, validation and defaults.
#include "test_harness.hpp"
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"

#include <dirent.h>
#include <algorithm>
#include <fstream>

static const std::string kTmp = TEST_TMP_DIR;

// A complete, valid system config (IWR1843, DCA1000 streaming).
static json base_config() {
    return json::parse(R"({
        "verbose": false,
        "TI_Radar_Config_Management": { "TI_Radar_config_path": "../radar/iwr1843.cfg" },
        "CLI_Controller": { "CLI_port": "/dev/ttyACM0" },
        "Streamer": {
            "serial_streaming": { "enabled": false, "data_port": "/dev/ttyACM1" },
            "DCA1000_streaming": {
                "enabled": true,
                "FPGA_IP": "192.168.33.180",
                "system_IP": "192.168.33.30",
                "data_port": 4098,
                "cmd_port": 4096
            },
            "save_to_file": true,
            "board_type": "IWR1843"
        }
    })");
}

static std::string write_text(const std::string& name, const std::string& text) {
    std::string path = kTmp + "/" + name;
    std::ofstream f(path);
    f << text;
    return path;
}

static std::string write_json(const std::string& name, const json& j) {
    return write_text(name, j.dump(4));
}

TEST_CASE(valid_config_fields) {
    SystemConfigReader r(write_json("sys_valid.json", base_config()));
    CHECK(r.initialized);
    CHECK(!r.get_verbose());
    CHECK_EQ(r.getBoardType(), std::string("IWR1843"));
    CHECK_EQ(r.getRadarCliPort(), std::string("/dev/ttyACM0"));
    CHECK_EQ(r.getRadarDataPort(), std::string("/dev/ttyACM1"));
    CHECK(!r.get_serial_streaming_enabled());
    CHECK(r.get_dca1000_streaming_enabled());
    CHECK_EQ(r.getDCAFpgaIP(), std::string("192.168.33.180"));
    CHECK_EQ(r.getDCASystemIP(), std::string("192.168.33.30"));
    CHECK_EQ(r.getDCADataPort(), 4098);
    CHECK_EQ(r.getDCACmdPort(), 4096);
    CHECK(r.get_save_to_file());
}

TEST_CASE(optional_fields_use_defaults) {
    SystemConfigReader r(write_json("sys_defaults.json", base_config()));
    CHECK_EQ(r.getRadarCliBaudRate(), 115200u);
    CHECK_EQ(r.getRadarCliTimeoutMs(), 100);
    CHECK_EQ(r.getRadarDataBaudRate(), 921600u);
    CHECK_EQ(r.getRadarDataTimeoutMs(), 1000);
    CHECK_EQ(r.getSDKMajorVersion(), 0);
    CHECK_EQ(r.getSDKMinorVersion(), 0);
}

TEST_CASE(optional_fields_override_defaults) {
    json j = base_config();
    j["CLI_Controller"]["baud_rate"] = 230400;
    j["CLI_Controller"]["cmd_timeout_ms"] = 5000;
    j["Streamer"]["serial_streaming"]["baud_rate"] = 3125000;
    j["Streamer"]["serial_streaming"]["timeout_ms"] = 2500;
    j["Streamer"]["SDK_version"] = "3.6";
    SystemConfigReader r(write_json("sys_override.json", j));
    CHECK(r.initialized);
    CHECK_EQ(r.getRadarCliBaudRate(), 230400u);
    CHECK_EQ(r.getRadarCliTimeoutMs(), 5000);
    CHECK_EQ(r.getRadarDataBaudRate(), 3125000u);
    CHECK_EQ(r.getRadarDataTimeoutMs(), 2500);
    CHECK_EQ(r.getSDKMajorVersion(), 3);
    CHECK_EQ(r.getSDKMinorVersion(), 6);
}

TEST_CASE(relative_radar_config_path_resolves_against_json_dir) {
    SystemConfigReader r(write_json("sys_relpath.json", base_config()));
    CHECK_EQ(r.getRadarConfigPath(), kTmp + "/../radar/iwr1843.cfg");
}

TEST_CASE(absolute_radar_config_path_is_kept) {
    json j = base_config();
    j["TI_Radar_Config_Management"]["TI_Radar_config_path"] = "/abs/path/radar.cfg";
    SystemConfigReader r(write_json("sys_abspath.json", j));
    CHECK(r.initialized);
    CHECK_EQ(r.getRadarConfigPath(), std::string("/abs/path/radar.cfg"));
}

TEST_CASE(all_board_types_accepted) {
    const char* boards[] = {"IWR1843", "IWR6843", "IWR1443"};
    for (const char* b : boards) {
        json j = base_config();
        j["Streamer"]["board_type"] = b;
        SystemConfigReader r(write_json("sys_board.json", j));
        CHECK(r.initialized);
        CHECK_EQ(r.getBoardType(), std::string(b));
    }
}

TEST_CASE(cascade_accepted_with_serial_only) {
    json j = base_config();
    j["Streamer"]["board_type"] = "AWR2243_CASCADE";
    j["Streamer"]["DCA1000_streaming"]["enabled"] = false;
    j["Streamer"]["serial_streaming"]["enabled"] = true;
    SystemConfigReader r(write_json("sys_cascade.json", j));
    CHECK(r.initialized);
    CHECK_EQ(r.getBoardType(), std::string("AWR2243_CASCADE"));
    CHECK(r.get_serial_streaming_enabled());
    CHECK(!r.get_dca1000_streaming_enabled());
}

TEST_CASE(cascade_with_dca1000_rejected) {
    json j = base_config();
    j["Streamer"]["board_type"] = "AWR2243_CASCADE";  // DCA1000 stays enabled
    SystemConfigReader r(write_json("sys_cascade_dca.json", j));
    CHECK(!r.initialized);
}

TEST_CASE(unknown_board_type_rejected) {
    json j = base_config();
    j["Streamer"]["board_type"] = "IWR9999";
    SystemConfigReader r(write_json("sys_badboard.json", j));
    CHECK(!r.initialized);
}

TEST_CASE(legacy_sdk_version_selects_board) {
    json j = base_config();
    j["Streamer"].erase("board_type");

    j["Streamer"]["SDK_version"] = "2.1";
    SystemConfigReader r2(write_json("sys_sdk2.json", j));
    CHECK(r2.initialized);
    CHECK_EQ(r2.getBoardType(), std::string("IWR1443"));
    CHECK_EQ(r2.getSDKMajorVersion(), 2);
    CHECK_EQ(r2.getSDKMinorVersion(), 1);

    j["Streamer"]["SDK_version"] = "3.6";
    SystemConfigReader r3(write_json("sys_sdk3.json", j));
    CHECK(r3.initialized);
    CHECK_EQ(r3.getBoardType(), std::string("IWR1843"));

    j["Streamer"]["SDK_version"] = "4.0";
    SystemConfigReader r4(write_json("sys_sdk4.json", j));
    CHECK(!r4.initialized);
}

TEST_CASE(neither_board_type_nor_sdk_version_rejected) {
    json j = base_config();
    j["Streamer"].erase("board_type");
    SystemConfigReader r(write_json("sys_noboard.json", j));
    CHECK(!r.initialized);
}

// Each required key, removed in turn, must leave the reader uninitialized.
TEST_CASE(missing_required_fields_rejected) {
    struct Removal { const char* label; const char* path[3]; };
    // path is up to 3 keys deep; the last non-null key is erased
    const Removal removals[] = {
        {"verbose", {"verbose", nullptr, nullptr}},
        {"Config_Management", {"TI_Radar_Config_Management", nullptr, nullptr}},
        {"config path", {"TI_Radar_Config_Management", "TI_Radar_config_path", nullptr}},
        {"CLI_Controller", {"CLI_Controller", nullptr, nullptr}},
        {"CLI_port", {"CLI_Controller", "CLI_port", nullptr}},
        {"Streamer", {"Streamer", nullptr, nullptr}},
        {"DCA1000_streaming", {"Streamer", "DCA1000_streaming", nullptr}},
        {"DCA enabled", {"Streamer", "DCA1000_streaming", "enabled"}},
        {"FPGA_IP", {"Streamer", "DCA1000_streaming", "FPGA_IP"}},
        {"system_IP", {"Streamer", "DCA1000_streaming", "system_IP"}},
        {"DCA data_port", {"Streamer", "DCA1000_streaming", "data_port"}},
        {"DCA cmd_port", {"Streamer", "DCA1000_streaming", "cmd_port"}},
        {"serial_streaming", {"Streamer", "serial_streaming", nullptr}},
        {"serial enabled", {"Streamer", "serial_streaming", "enabled"}},
        {"serial data_port", {"Streamer", "serial_streaming", "data_port"}},
        {"save_to_file", {"Streamer", "save_to_file", nullptr}},
    };
    for (const Removal& rm : removals) {
        json j = base_config();
        json* node = &j;
        int depth = 0;
        while (depth + 1 < 3 && rm.path[depth + 1] != nullptr) {
            node = &(*node)[rm.path[depth]];
            depth++;
        }
        node->erase(rm.path[depth]);
        SystemConfigReader r(write_json("sys_missing.json", j));
        if (r.initialized) {
            th::fail(__FILE__, __LINE__, std::string("accepted config missing: ") + rm.label);
        }
        th::counters().checks++;
    }
}

TEST_CASE(nonexistent_file_is_not_initialized) {
    SystemConfigReader r(kTmp + "/definitely_missing.json");
    CHECK(!r.initialized);
}

TEST_CASE(malformed_json_throws) {
    // Characterization: a syntax error escapes as nlohmann parse_error rather
    // than being reported through `initialized`.
    std::string path = write_text("sys_malformed.json", "{ \"verbose\": tru");
    CHECK_THROWS(SystemConfigReader r(path), json::parse_error);
}

TEST_CASE(wrong_value_type_throws) {
    json j = base_config();
    j["verbose"] = "yes";
    std::string path = write_json("sys_wrongtype.json", j);
    CHECK_THROWS(SystemConfigReader r(path), json::type_error);
}

TEST_CASE(copy_and_assignment_preserve_values) {
    SystemConfigReader a(write_json("sys_copy.json", base_config()));
    SystemConfigReader b(a);
    CHECK(b.initialized);
    CHECK_EQ(b.getBoardType(), std::string("IWR1843"));
    CHECK_EQ(b.getDCADataPort(), 4098);
    SystemConfigReader c;
    c = a;
    CHECK(c.initialized);
    CHECK_EQ(c.getRadarConfigPath(), a.getRadarConfigPath());
}

// Every shipped system config must parse and point at a parseable radar cfg.
TEST_CASE(all_shipped_system_configs_load) {
    const std::string dir = std::string(CONFIG_DIR) + "/system";
    std::vector<std::string> files;
    DIR* d = opendir(dir.c_str());
    CHECK(d != nullptr);
    if (d == nullptr) return;
    while (dirent* e = readdir(d)) {
        std::string n = e->d_name;
        if (n.size() > 5 && n.substr(n.size() - 5) == ".json") files.push_back(n);
    }
    closedir(d);
    std::sort(files.begin(), files.end());
    CHECK(files.size() > 10);

    for (const std::string& f : files) {
        const std::string path = dir + "/" + f;
        try {
            SystemConfigReader r(path);
            if (!r.initialized) {
                th::fail(f.c_str(), 0, "system config not accepted");
                continue;
            }
            const std::string board = r.getBoardType();
            CHECK(board == "IWR1843" || board == "IWR6843" || board == "IWR1443" ||
                  board == "AWR2243_CASCADE");
            RadarConfigReader rc(r.getRadarConfigPath());
            if (!rc.initialized) {
                th::fail(f.c_str(), 0, "radar cfg not readable: " + r.getRadarConfigPath());
                continue;
            }
            CHECK(rc.get_bytes_per_frame() > 0);
        } catch (const std::exception& ex) {
            th::fail(f.c_str(), 0, std::string("threw: ") + ex.what());
        }
    }
}

TEST_MAIN()
