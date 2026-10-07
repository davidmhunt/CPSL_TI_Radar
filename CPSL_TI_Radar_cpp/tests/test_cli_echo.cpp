// The cli echo line (directive gui-34 Step 2): one info-level line per command
// sent to the board, written after its reply. radar_gui/driver.py parses it,
// so the four forms (DONE, ERROR, TIMEOUT, skip) and the tags are pinned here.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "fake_transports.hpp"
#include "CLIController.hpp"
#include "Log.hpp"

#include <fstream>
#include <iterator>
#include <mutex>

namespace {

// Captures every message (any level) while alive; sets the level to info.
class LogLines {
public:
    LogLines() {
        cpsl::radar::set_log_level(cpsl::radar::LogLevel::info);
        cpsl::radar::set_log_sink([this](cpsl::radar::LogLevel, const std::string& m) {
            std::lock_guard<std::mutex> l(m_);
            lines.push_back(m);
        });
    }
    ~LogLines() { cpsl::radar::set_log_sink(nullptr); }
    std::vector<std::string> get() {
        std::lock_guard<std::mutex> l(m_);
        return lines;
    }
    bool has(const std::string& s) {
        for (const std::string& l : get())
            if (l == s) return true;
        return false;
    }

private:
    std::mutex m_;
    std::vector<std::string> lines;
};

// IWR1843 system config pointing at a cfg written here.
SystemConfigReader config_with_cfg(const std::string& name, const std::string& cfg_text) {
    const std::string base = dca_test::write_system_config(name, dca_test::tmp_dir(), false);
    nlohmann::json j;
    {
        std::ifstream f(base);
        j = nlohmann::json::parse(f);
    }
    const std::string cfg = dca_test::tmp_dir() + "/" + name + ".cfg";
    {
        // the real test cfg (the config reader validates it) + this test's extra lines
        std::ifstream base_cfg(std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg");
        std::string text((std::istreambuf_iterator<char>(base_cfg)), std::istreambuf_iterator<char>());
        std::ofstream(cfg) << text << "\n" << cfg_text;
    }
    j["radar_cfg"] = cfg;
    j["board_overrides"] = {{"cfg_dialect", {{"skip_commands", {"calibData"}}}}};
    const std::string path = dca_test::tmp_dir() + "/" + name + "_sys.json";
    std::ofstream(path) << j.dump();
    return SystemConfigReader(path);
}

}  // namespace

// First echo line for `cmd` ("" if none): "cli [<tag>] <cmd> -> ..." with the tag
// returned in `tag`.
static std::string echo_for(const std::vector<std::string>& lines, const std::string& cmd, std::string& tag) {
    for (const std::string& s : lines) {
        if (s.rfind("cli [", 0) != 0) continue;
        const size_t rb = s.find("] ");
        if (rb == std::string::npos) continue;
        const std::string rest = s.substr(rb + 2);
        if (rest.rfind(cmd + " -> ", 0) == 0) {
            tag = s.substr(5, rb - 5);
            return rest.substr(cmd.size() + 4);
        }
    }
    return "";
}

TEST_CASE(done_skip_error_and_tags) {
    // the base cfg is 8 commands (sensorStop .. lvdsStreamCfg); sensorStart is dropped
    SystemConfigReader sys = config_with_cfg("echo_a", "calibData 0 0 0\nbadCfg 1\n");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    fake->reply_text["badCfg 1"] = "Error: bad \"arg\"\r\nError -1\r\n";  // no Done: rejected
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    LogLines log;
    CHECK(!cli.send_config_to_IWR());  // badCfg failed
    CHECK(cli.sendStartCommand());
    CHECK(cli.sendStopCommand());
    const std::vector<std::string> l = log.get();
    for (const std::string& s : l) std::cout << "  log: " << s << "\n";
    CHECK(log.has("cli [skip] calibData 0 0 0 (skip_commands)"));
    std::string tag;
    std::string r = echo_for(l, "channelCfg 15 5 0", tag);
    CHECK_EQ(tag, std::string("2/9"));
    CHECK(r.rfind("DONE (", 0) == 0 && r.back() == ')');  // no reply text on a plain Done
    r = echo_for(l, "badCfg 1", tag);
    CHECK_EQ(tag, std::string("9/9"));
    CHECK(r.rfind("ERROR (", 0) == 0);
    CHECK(r.find(" ms) \"Error: bad 'arg' | Error -1\"") != std::string::npos);
    r = echo_for(l, "sensorStart", tag);
    CHECK_EQ(tag, std::string("start"));
    CHECK(r.rfind("DONE (", 0) == 0);
    r = echo_for(l, "sensorStop", tag);  // the first one is the cfg's own sensorStop line
    CHECK_EQ(tag, std::string("1/9"));
    std::vector<std::string> tail(l.end() - 1, l.end());
    r = echo_for(tail, "sensorStop", tag);
    CHECK_EQ(tag, std::string("stop"));
}

TEST_CASE(timeout_without_reply_has_no_quoted_part) {
    SystemConfigReader sys = config_with_cfg("echo_b", "");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    fake->fail_from_now(FakeCli::Fail::no_reply);
    LogLines log;
    CHECK(!cli.sendStopCommand());
    CHECK(log.has("cli [stop] sensorStop -> TIMEOUT no 'Done' in " + std::to_string(cli.stop_timeout_ms()) + " ms"));
}

TEST_CASE(partial_reply_without_error_is_a_timeout_with_text) {
    SystemConfigReader sys = config_with_cfg("echo_c", "foo 1 2\n");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    fake->reply_text["foo 1 2"] = "partial\r\n";
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    LogLines log;
    CHECK(!cli.send_config_to_IWR());
    for (const std::string& s : log.get()) std::cout << "  log: " << s << "\n";
    CHECK(log.has("cli [9/9] foo 1 2 -> TIMEOUT no 'Done' in 100 ms \"partial\""));
}

TEST_CASE(reply_is_capped_at_200_chars) {
    SystemConfigReader sys = config_with_cfg("echo_d", "foo\n");
    std::shared_ptr<FakeCli> fake = std::make_shared<FakeCli>();
    fake->reply_text["foo"] = "Error: " + std::string(500, 'x') + "\r\n";
    CLIController cli;
    CHECK(cli.initialize(sys, fake));
    LogLines log;
    CHECK(!cli.send_config_to_IWR());
    std::string tag;
    const std::string r = echo_for(log.get(), "foo", tag);
    const size_t q = r.find(" ms) \"");
    CHECK(q != std::string::npos);
    const std::string text = r.substr(q + 6, r.size() - (q + 6) - 1);  // between the quotes
    CHECK_EQ(text.size(), size_t(203));  // 200 chars + "..."
    CHECK_EQ(text.substr(200), std::string("..."));
}

TEST_MAIN()
