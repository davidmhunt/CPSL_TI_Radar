// FirmwareDescriptor: strict loading of config/firmware/*.json (gui-04 Step 1).
// Every shipped descriptor must load; the rejection cases pin the strictness
// (duplicate keys, unknown keys, bad types, inconsistent board sets).
#include "test_harness.hpp"
#include "FirmwareDescriptor.hpp"

#include <dirent.h>

#include <algorithm>
#include <fstream>
#include <string>
#include <vector>

using cpsl::radar::FirmwareDescriptor;
using nlohmann::json;

static const std::string kFirmware = std::string(CONFIG_DIR) + "/firmware";
static const std::string kTmp = TEST_TMP_DIR;

static json read_json(const std::string& path) {
    std::ifstream f(path);
    return json::parse(f);
}

static std::string write_text(const std::string& name, const std::string& text) {
    std::string path = kTmp + "/" + name;
    std::ofstream f(path);
    f << text;
    return path;
}

// from_json on a shipped descriptor after `mutate`; returns the error ("" if it loaded)
template <class F>
static std::string load_mutated(const std::string& id, F mutate) {
    json j = read_json(kFirmware + "/" + id + ".json");
    mutate(j);
    FirmwareDescriptor d;
    std::string err;
    if (FirmwareDescriptor::from_json(j, id, id + ".json", d, err)) return "";
    std::cout << "    rejected as expected: " << err << std::endl;
    return err;
}

static bool has(const std::string& s, const std::string& sub) { return s.find(sub) != std::string::npos; }

TEST_CASE(every_shipped_descriptor_loads) {
    std::vector<std::string> ids;
    if (DIR* d = opendir(kFirmware.c_str())) {
        while (dirent* e = readdir(d)) {
            std::string n = e->d_name;
            if (n.size() > 5 && n.compare(n.size() - 5, 5, ".json") == 0) ids.push_back(n.substr(0, n.size() - 5));
        }
        closedir(d);
    }
    CHECK(ids.size() >= 4);
    for (const std::string& id : ids) {
        FirmwareDescriptor fw;
        std::string err;
        const bool ok = FirmwareDescriptor::load_by_id(kFirmware, id, fw, err);
        if (!ok) std::cerr << "load failed: " << err << std::endl;
        CHECK(ok);
        CHECK_EQ(fw.id, id);
        CHECK(!fw.templates.empty());
        CHECK_EQ(fw.outputs.size(), fw.templates.size());
        CHECK(!fw.limits.empty());
    }
}

TEST_CASE(demo_content) {
    FirmwareDescriptor fw;
    std::string err;
    CHECK(FirmwareDescriptor::load_by_id(kFirmware, "demo", fw, err));
    CHECK(fw.supports_board("IWR1843"));
    CHECK(!fw.supports_board("AWR2243_CASCADE"));
    CHECK(fw.outputs.at("IWR1843").tlv);
    CHECK(fw.enable_serial);
    CHECK(!fw.enable_dca1000);
    const auto& n_tx = fw.limits.at("IWR1843").at("n_tx");
    CHECK_EQ(n_tx.level, std::string("error"));
    CHECK(n_tx.value.is_number());
    CHECK(!n_tx.source.empty());
}

TEST_CASE(sar_driver_board_alias) {
    FirmwareDescriptor fw;
    std::string err;
    CHECK(FirmwareDescriptor::load_by_id(kFirmware, "iwr1843_sar_lvds", fw, err));
    CHECK_EQ(fw.driver_board_for("IWR1843"), std::string("IWR1843_SAR"));
    CHECK_EQ(fw.gui_board_for("IWR1843_SAR"), std::string("IWR1843"));
    // a board without a driver_board entry maps to itself
    CHECK_EQ(fw.driver_board_for("IWR6843"), std::string("IWR6843"));
    CHECK_EQ(fw.gui_board_for("IWR1843"), std::string("IWR1843"));
}

TEST_CASE(gui_only_keys_are_accepted_and_listed_once) {
    const auto& keys = FirmwareDescriptor::gui_only_keys();
    CHECK(keys.count("identify") == 0);  // parsed strictly since gui-33 (test_firmware_identity)
    CHECK(keys.count("mimo") == 1);
    CHECK(keys.count("lvds_data_fmts") == 1);
    // the cascade limit keys added in 3a032e0 are plain limit entries
    FirmwareDescriptor fw;
    std::string err;
    CHECK(FirmwareDescriptor::load_by_id(kFirmware, "cascade_ddm", fw, err));
    CHECK(fw.limits.at("AWR2243_CASCADE").count("l2_heap_bytes") == 1);
    CHECK(fw.limits.at("AWR2243_CASCADE").count("l3_cube_bytes") == 1);
    // an unlisted extra key is not a GUI key: rejected
    CHECK(has(load_mutated("demo", [](json& j) { j["detection"] = 1; }), "/detection: unknown key"));
}

TEST_CASE(rejections) {
    CHECK(has(load_mutated("demo", [](json& j) { j["extra"] = 1; }), "/extra: unknown key"));
    CHECK(has(load_mutated("demo", [](json& j) { j.erase("limits"); }), "/limits: missing required key"));
    CHECK(has(load_mutated("demo", [](json& j) { j["schema"] = 1; }), "unsupported schema 1"));
    CHECK(has(load_mutated("demo", [](json& j) { j["id"] = "other"; }), "must match the file name"));
    CHECK(has(load_mutated("demo", [](json& j) { j["templates"] = json::object(); }), "/templates"));
    CHECK(has(load_mutated("demo", [](json& j) { j["outputs"].erase("IWR1443"); }), "/outputs/IWR1443: missing"));
    CHECK(has(load_mutated("demo", [](json& j) { j["outputs"]["IWR9999"] = {{"tlv", true}, {"lvds", true}}; }),
              "/outputs/IWR9999: board is not in templates"));
    CHECK(has(load_mutated("demo", [](json& j) { j["outputs"]["IWR1843"]["tlv"] = "yes"; }),
              "/outputs/IWR1843/tlv: expected true or false"));
    CHECK(has(load_mutated("demo", [](json& j) { j["outputs"]["IWR1843"]["extra"] = true; }),
              "/outputs/IWR1843/extra: unknown key"));
    CHECK(has(load_mutated("demo", [](json& j) { j["system_enables"].erase("serial"); }),
              "/system_enables/serial: missing"));
    CHECK(has(load_mutated("demo", [](json& j) { j["driver_board"] = {{"IWR9999", "X"}}; }),
              "/driver_board/IWR9999: board is not in templates"));
    CHECK(has(load_mutated("demo", [](json& j) { j["driver_board"] = {{"IWR1843", "X"}, {"IWR6843", "X"}}; }),
              "mapped twice"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR1843"]["n_tx"]["level"] = "fatal"; }),
              "/limits/IWR1843/n_tx/level: \"fatal\" is not one of: error, warning"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR1843"]["n_tx"].erase("source"); }),
              "/limits/IWR1843/n_tx/source: missing"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR1843"]["n_tx"]["confidence"] = "sure"; }),
              "/limits/IWR1843/n_tx/confidence"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR1843"]["n_tx"]["value"] = nullptr; }),
              "/limits/IWR1843/n_tx/value"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR1843"]["n_tx"]["why"] = 1; }),
              "/limits/IWR1843/n_tx/why: unknown key"));
    CHECK(has(load_mutated("demo", [](json& j) { j["limits"]["IWR9999"] = json::object(); }),
              "/limits/IWR9999: board is not in templates"));
}

TEST_CASE(file_level_rejections) {
    FirmwareDescriptor fw;
    std::string err;

    // duplicate key (nlohmann would silently keep the last one)
    std::string p = write_text("fw_dup.json", R"({"schema": 2, "schema": 2})");
    CHECK(!FirmwareDescriptor::load(p, fw, err));
    CHECK(has(err, "duplicate key \"schema\""));

    // duplicate key nested in a limit entry
    std::ifstream f(kFirmware + "/demo.json");
    std::string text((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    const std::string needle = "\"n_tx\": {";
    std::string::size_type at = text.find(needle);
    CHECK(at != std::string::npos);
    text.insert(at + needle.size(), "\"level\": \"error\", ");
    p = write_text("demo.json", text);
    CHECK(!FirmwareDescriptor::load(p, fw, err));
    CHECK(has(err, "duplicate key \"level\""));

    p = write_text("fw_notjson.json", "{ not json");
    CHECK(!FirmwareDescriptor::load(p, fw, err));
    CHECK(has(err, "not valid JSON"));

    CHECK(!FirmwareDescriptor::load(kTmp + "/missing_fw.json", fw, err));
    CHECK(has(err, "cannot open firmware descriptor"));

    CHECK(!FirmwareDescriptor::load_by_id(kFirmware, "../boards/IWR1843", fw, err));
    CHECK(has(err, "plain id"));
    CHECK(!FirmwareDescriptor::load_by_id(kFirmware, "", fw, err));
}

TEST_MAIN()
