// Firmware identity check (directive gui-33 Step 2).
//
// Part 1: the pure matcher over tests/data/fw_replies/manifest.json, the same
// cases radar_gui/fwident.py runs in pytest (parity), plus the identify block's
// strict loading. Part 2: Radar::configure on a scripted CLI (FakeCli): match,
// mismatch (nothing but the probes is written), warn, timeout, off, the cascade
// (skipped) and skip_configure (no CLI traffic at all). No hardware.
#include "test_harness.hpp"
#include "fake_transports.hpp"
#include "uart_test_frames.hpp"

#include "FirmwareIdentity.hpp"
#include "Radar.hpp"

#include <cstdlib>
#include <fstream>
#include <iterator>
#include <sys/stat.h>

using namespace cpsl::radar;
using nlohmann::json;

namespace {

const std::string kFirmwareDir = std::string(CONFIG_DIR) + "/firmware";
const std::string kBoardsDir = std::string(CONFIG_DIR) + "/boards";
const std::string kFixtures = std::string(TEST_DATA_DIR) + "/fw_replies";

std::string read_file(const std::string& path) {
    std::ifstream f(path);
    return std::string(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
}

bool has(const std::string& hay, const std::string& needle) { return hay.find(needle) != std::string::npos; }

// Captures every log message (any level) while alive.
class Lines {
public:
    Lines() {
        set_log_level(LogLevel::info);
        set_log_sink([this](LogLevel l, const std::string& m) {
            std::lock_guard<std::mutex> lock(m_);
            all.push_back(m);
            if (l == LogLevel::warn) warns.push_back(m);
        });
    }
    ~Lines() { set_log_sink(nullptr); }
    bool has_line(const std::string& s) {
        std::lock_guard<std::mutex> lock(m_);
        for (const std::string& l : all) if (l == s) return true;
        return false;
    }
    bool has_warn_containing(const std::string& s) {
        std::lock_guard<std::mutex> lock(m_);
        for (const std::string& l : warns) if (has(l, s)) return true;
        return false;
    }
    bool warn_line(const std::string& s) {
        std::lock_guard<std::mutex> lock(m_);
        for (const std::string& l : warns) if (l == s) return true;
        return false;
    }

private:
    std::mutex m_;
    std::vector<std::string> all, warns;
};

}  // namespace

// ---- Part 1: matcher parity with fwident.py ----

TEST_CASE(manifest_verdicts_match_the_python_matcher) {
    const json manifest = json::parse(read_file(kFixtures + "/manifest.json"));
    int n = 0;
    for (const json& c : manifest.at("cases")) {
        const std::string fw = c.at("fw"), board = c.at("board"), id = c.at("id");
        FirmwareDescriptor d;
        std::string err;
        CHECK(FirmwareDescriptor::load_by_id(kFirmwareDir, fw, d, err));
        BoardDescriptor b;
        CHECK(BoardDescriptor::load_by_name(kBoardsDir, board, b, err));
        auto it = d.identify.find(board);
        const FirmwareDescriptor::Identify* entry = it == d.identify.end() ? nullptr : &it->second;
        std::map<std::string, std::string> replies;
        for (auto r = c.at("replies").begin(); r != c.at("replies").end(); ++r) {
            if (!r.value().is_null()) replies[r.key()] = strip_fixture(read_file(kFixtures + "/" + r.value().get<std::string>()));
        }
        const IdentityResult res = match_firmware_identity(entry, b.lifecycle.config_once_per_boot, replies);
        std::cout << "    " << id << ": " << to_string(res.verdict) << " found=" << res.found << std::endl;
        CHECK_EQ(std::string(to_string(res.verdict)), c.at("verdict").get<std::string>());
        n++;
    }
    CHECK(n > 0 && static_cast<size_t>(n) == manifest.at("cases").size());
}

TEST_CASE(match_reports_the_shown_fields_in_display_order) {
    FirmwareDescriptor d;
    std::string err;
    CHECK(FirmwareDescriptor::load_by_id(kFirmwareDir, "demo", d, err));
    std::map<std::string, std::string> replies = {
        {"version", strip_fixture(read_file(kFixtures + "/demo_IWR1843_version.txt"))},
        {"sarStats", strip_fixture(read_file(kFixtures + "/demo_IWR1843_sarStats.txt"))}};
    const IdentityResult res = match_firmware_identity(&d.identify.at("IWR1843"), false, replies);
    CHECK_EQ(std::string(to_string(res.verdict)), std::string("match"));
    CHECK_EQ(res.found, std::string("platform=xWR18xx sdk=03.06.02.00 device=IWR18xx ES 02.00"));
}

TEST_CASE(identify_block_is_loaded_strictly) {
    json base = json::parse(read_file(kFirmwareDir + "/demo.json"));
    auto load = [&](auto mutate) {
        json j = base;
        mutate(j);
        FirmwareDescriptor d;
        std::string err;
        return FirmwareDescriptor::from_json(j, "demo", "demo.json", d, err) ? std::string() : err;
    };
    CHECK_EQ(load([](json&) {}), std::string());
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["extra"] = 1; }), "/identify/IWR1843/extra: unknown key"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["probes"][0]["extra"] = 1; }), "/probes/0/extra: unknown key"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["probes"][0]["require"] = {"(unclosed"}; }), "bad regex"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["level"] = "guess"; }), "/level"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"].erase("flash_hint"); }), "/flash_hint: missing"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["timeout_ms"] = 0; }), "/timeout_ms"));
    CHECK(has(load([](json& j) { j["identify"]["IWR9999"] = j["identify"]["IWR1843"]; }), "not in templates"));
    CHECK(has(load([](json& j) { j["identify"]["IWR1843"]["probes"] = json::array(); }), "/probes"));
    CHECK(has(load([](json& j) {
                  j["identify"]["IWR1843"]["probes"] = {{{"cmd", "version"}, {"show", {{"a", "(x)"}}}}};
              }),
              "needs a require or reject"));
}

// ---- Part 2: Radar::configure over a scripted CLI ----

namespace {

const char* kVersionReply = "Platform                : xWR18xx\r\nmmWave SDK Version      : 03.06.02.00\r\n"
                            "Device Info             : IWR18xx ES 02.00\r\nDone\r\n\r\n";
const char* kVersion68Reply = "Platform                : xWR68xx\r\nmmWave SDK Version      : 03.06.02.00\r\n"
                              "Device Info             : IWR68xx ES 02.00\r\nDone\r\n\r\n";
const char* kNotRecognized = "'sarStats' is not recognized as a CLI command\r\n\r\n";

struct Rig {
    std::shared_ptr<FakeCli> cli = std::make_shared<FakeCli>();
    std::shared_ptr<uart_test::FakeDataPort> data = std::make_shared<uart_test::FakeDataPort>();
    std::unique_ptr<Radar> radar;

    // `firmware`: the system JSON's firmware key ("" = none); `check`: runtime.firmware_check ("" = unset)
    Rig(const std::string& name, const std::string& board, const std::string& firmware, const std::string& check,
        bool skip = false) {
        const std::string path = uart_test::write_serial_config(name, TEST_TMP_DIR, board, 300);
        json j = json::parse(read_file(path));
        if (!firmware.empty()) j["firmware"] = firmware;
        j["runtime"]["firmware_check"] = check.empty() ? "auto" : check;  // the writer defaults to "off"
        std::ofstream(path) << j.dump(2);
        Result<RadarConfig> cfg = RadarConfig::load(path);
        CHECK(static_cast<bool>(cfg));
        if (!cfg) {
            std::cerr << cfg.status.message << std::endl;
            return;
        }
        if (skip) cfg->set_skip_configure(true);
        Transports t;
        t.cli = cli;
        t.data = data;
        auto r = Radar::open(*cfg, t);
        CHECK(static_cast<bool>(r));
        if (r) radar = std::move(*r);
        else std::cerr << r.status.message << std::endl;
    }
    // demo on an IWR1843: the stock image's answers
    void answer_as_demo() {
        cli->reply_text["version"] = kVersionReply;
        cli->reply_text["sarStats"] = kNotRecognized;
    }
    // a cfg line was written (anything but the probes)
    bool cfg_written() {
        for (const std::string& l : cli->attempted)
            if (l != "version\n" && l != "sarStats\n") return true;
        return false;
    }
};

}  // namespace

TEST_CASE(match_sends_the_probes_then_the_cfg) {
    Lines log;
    Rig rig("fwid_match", "IWR1843", "demo", "");
    rig.answer_as_demo();
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    const Status s = rig.radar->configure();
    CHECK(static_cast<bool>(s));
    CHECK(rig.cli->attempted.size() > 2);
    CHECK_EQ(rig.cli->attempted[0], std::string("version\n"));
    CHECK_EQ(rig.cli->attempted[1], std::string("sarStats\n"));
    CHECK(rig.cfg_written());
    CHECK(log.has_line("firmware: match expected=demo found=platform=xWR18xx sdk=03.06.02.00 device=IWR18xx ES 02.00"));
}

TEST_CASE(mismatch_is_fatal_and_no_cfg_line_is_written) {
    Lines log;
    Rig rig("fwid_mismatch", "IWR1843", "demo", "");
    rig.cli->reply_text["version"] = kVersion68Reply;  // an xWR68xx image answering on an 1843 JSON
    rig.cli->reply_text["sarStats"] = kNotRecognized;
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    const Status s = rig.radar->configure();
    CHECK(s.code == Code::firmware_mismatch);
    CHECK_EQ(std::string(to_string(s.code)), std::string("firmware_mismatch"));
    std::cout << "    " << s.message << std::endl;
    CHECK(has(s.message, "firmware mismatch on /dev/null-not-opened: system JSON expects demo (IWR1843), "
                         "board answered platform=xWR68xx"));
    CHECK(has(s.message, "Flash it: ./fw flash ti_stock_demos"));
    CHECK(has(s.message, "or set runtime.firmware_check \"warn\""));
    CHECK(!rig.cfg_written());
    CHECK(log.has_line("firmware: mismatch expected=demo found=platform=xWR68xx sdk=03.06.02.00 device=IWR68xx ES 02.00"));
    // nothing was spent: configure() can be called again
    CHECK(rig.radar->configure().code == Code::firmware_mismatch);
}

TEST_CASE(warn_policy_turns_a_mismatch_into_a_warning_and_sends_the_cfg) {
    Lines log;
    Rig rig("fwid_warn", "IWR1843", "demo", "warn");
    rig.cli->reply_text["version"] = kVersion68Reply;
    rig.cli->reply_text["sarStats"] = kNotRecognized;
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    CHECK(static_cast<bool>(rig.radar->configure()));
    CHECK(rig.cfg_written());
    CHECK(log.warn_line("firmware: mismatch expected=demo found=platform=xWR68xx sdk=03.06.02.00 device=IWR68xx ES 02.00"));
}

TEST_CASE(no_reply_is_a_warning_and_the_cfg_is_sent) {
    Lines log;
    // a short probe timeout through a copy of the descriptor (the shipped one waits 3 s per probe)
    const std::string dir = std::string(TEST_TMP_DIR) + "/fwid_fwdir";
    mkdir(dir.c_str(), 0755);
    json d = json::parse(read_file(kFirmwareDir + "/demo.json"));
    d["identify"]["IWR1843"]["timeout_ms"] = 60;
    std::ofstream(dir + "/demo.json") << d.dump(2);
    setenv(SystemConfigReader::kFirmwareDirEnv, dir.c_str(), 1);
    Rig rig("fwid_timeout", "IWR1843", "demo", "");
    unsetenv(SystemConfigReader::kFirmwareDirEnv);
    rig.cli->silent_cmds = {"version", "sarStats"};
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    const Status s = rig.radar->configure();
    CHECK(static_cast<bool>(s));
    CHECK(rig.cfg_written());
    CHECK(log.warn_line("firmware: unknown expected=demo found=no reply"));
    CHECK(log.has_warn_containing("could not confirm the firmware"));
}

TEST_CASE(off_writes_no_version) {
    Lines log;
    Rig rig("fwid_off", "IWR1843", "demo", "off");
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    CHECK(static_cast<bool>(rig.radar->configure()));
    CHECK_EQ(rig.cli->count("version\n"), static_cast<size_t>(0));
    CHECK_EQ(rig.cli->count("sarStats\n"), static_cast<size_t>(0));
    CHECK(rig.cfg_written());
    CHECK(!log.has_line("firmware: match expected=demo found=no reply"));
}

TEST_CASE(config_without_a_firmware_key_is_refused) {
    // gui-04 Step 3a: the key is required, so there is no "asks nothing" mode any more
    const std::string path = uart_test::write_serial_config("fwid_nokey", TEST_TMP_DIR, "IWR1843", 300);
    json j = json::parse(read_file(path));
    j.erase("firmware");
    std::ofstream(path) << j.dump(2);
    Result<RadarConfig> cfg = RadarConfig::load(path);
    CHECK(!static_cast<bool>(cfg));
}

TEST_CASE(cascade_is_skipped_and_sends_the_cfg) {
    Lines log;
    Rig rig("fwid_cascade", "AWR2243_CASCADE", "cascade_ddm", "");
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    const Status s = rig.radar->configure();
    CHECK(static_cast<bool>(s));
    CHECK_EQ(rig.cli->count("version\n"), static_cast<size_t>(0));
    CHECK(rig.cfg_written());
    CHECK(log.has_line("firmware: skipped expected=cascade_ddm found=not queried"));
}

TEST_CASE(skip_configure_sends_nothing_at_all) {
    Lines log;
    Rig rig("fwid_skipcfg", "IWR1843", "demo", "", true);
    CHECK(rig.radar != nullptr);
    if (!rig.radar) return;
    CHECK(static_cast<bool>(rig.radar->configure()));
    CHECK_EQ(rig.cli->writes(), static_cast<size_t>(0));
}

TEST_CASE(runtime_firmware_check_rejects_an_unknown_value) {
    const std::string path = uart_test::write_serial_config("fwid_badpolicy", TEST_TMP_DIR, "IWR1843", 300);
    json j = json::parse(read_file(path));
    j["runtime"]["firmware_check"] = "sometimes";
    std::ofstream(path) << j.dump(2);
    SystemConfigReader sys(path);
    CHECK(!sys.initialized);
    bool named = false;
    for (const auto& i : sys.getIssues()) named = named || has(i.message, "/runtime/firmware_check");
    CHECK(named);
}

TEST_CASE(a_once_per_boot_entry_must_say_once_safe) {
    const std::string dir = std::string(TEST_TMP_DIR) + "/fwid_fwdir2";
    mkdir(dir.c_str(), 0755);
    json d = json::parse(read_file(kFirmwareDir + "/cascade_ddm.json"));
    d["identify"]["AWR2243_CASCADE"].erase("once_safe");
    std::ofstream(dir + "/cascade_ddm.json") << d.dump(2);
    setenv(SystemConfigReader::kFirmwareDirEnv, dir.c_str(), 1);
    const std::string path = uart_test::write_serial_config("fwid_nosafe", TEST_TMP_DIR, "AWR2243_CASCADE", 300);
    json j = json::parse(read_file(path));
    j["firmware"] = "cascade_ddm";
    std::ofstream(path) << j.dump(2);
    SystemConfigReader sys(path);
    unsetenv(SystemConfigReader::kFirmwareDirEnv);
    CHECK(!sys.initialized);
    bool named = false;
    for (const auto& i : sys.getIssues()) named = named || has(i.message, "/identify/AWR2243_CASCADE/once_safe");
    CHECK(named);
}

TEST_CASE(validate_note_lists_the_probes_and_sends_nothing) {
    FirmwareDescriptor d;
    std::string err;
    CHECK(FirmwareDescriptor::load_by_id(kFirmwareDir, "demo", d, err));
    CHECK_EQ(describe_firmware_check(&d.identify.at("IWR1843"), false, FirmwareCheck::automatic),
             std::string("firmware check: version, sarStats before the cfg (level bench)"));
    CHECK_EQ(describe_firmware_check(&d.identify.at("IWR1843"), false, FirmwareCheck::off),
             std::string("firmware check: off (runtime.firmware_check)"));
    FirmwareDescriptor c;
    CHECK(FirmwareDescriptor::load_by_id(kFirmwareDir, "cascade_ddm", c, err));
    CHECK(has(describe_firmware_check(&c.identify.at("AWR2243_CASCADE"), true, FirmwareCheck::automatic),
              "skipped: once-per-power-up, not once_safe"));
}

TEST_MAIN()
