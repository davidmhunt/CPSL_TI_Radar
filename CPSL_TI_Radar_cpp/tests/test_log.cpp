// Log sink and level filtering (directive core-13 Step 1; core-10 review S5:
// log_level error/warn behaved like info).
#include "test_harness.hpp"
#include "Log.hpp"
#include "RadarConfigReader.hpp"
#include "Status.hpp"

#include <mutex>
#include <string>
#include <utility>
#include <vector>

using cpsl::radar::LogLevel;

namespace {

struct Captured {
    std::mutex m;
    std::vector<std::pair<LogLevel, std::string>> lines;
};

Captured& captured() {
    static Captured c;
    return c;
}

void capture_sink() {
    captured().lines.clear();
    cpsl::radar::set_log_sink([](LogLevel l, const std::string& msg) {
        std::lock_guard<std::mutex> lock(captured().m);
        captured().lines.emplace_back(l, msg);
    });
}

// one message at every level; returns how many reached the sink
size_t emit_all() {
    captured().lines.clear();
    cpsl::radar::log_error("e");
    cpsl::radar::log_warn("w");
    cpsl::radar::log_info("i");
    cpsl::radar::log_debug("d");
    return captured().lines.size();
}

}  // namespace

TEST_CASE(each_level_filters_distinctly) {
    capture_sink();
    cpsl::radar::set_log_level(LogLevel::error);
    CHECK_EQ(emit_all(), size_t(1));
    CHECK(captured().lines[0].first == LogLevel::error);
    cpsl::radar::set_log_level(LogLevel::warn);
    CHECK_EQ(emit_all(), size_t(2));
    CHECK(captured().lines[1].first == LogLevel::warn);
    cpsl::radar::set_log_level(LogLevel::info);
    CHECK_EQ(emit_all(), size_t(3));
    cpsl::radar::set_log_level(LogLevel::debug);
    CHECK_EQ(emit_all(), size_t(4));
    CHECK_EQ(captured().lines[3].second, std::string("d"));
    cpsl::radar::set_log_level(LogLevel::info);
    cpsl::radar::set_log_sink(nullptr);
}

TEST_CASE(arguments_are_formatted_into_one_message) {
    capture_sink();
    cpsl::radar::log_warn("port ", "/dev/x", ": ", 42, " ms");
    CHECK_EQ(captured().lines.size(), size_t(1));
    CHECK_EQ(captured().lines[0].second, std::string("port /dev/x: 42 ms"));
    cpsl::radar::set_log_sink(nullptr);
}

TEST_CASE(a_throwing_sink_does_not_escape) {
    cpsl::radar::set_log_sink([](LogLevel, const std::string&) { throw 1; });
    bool threw = false;
    try {
        cpsl::radar::log_error("x");
    } catch (...) {
        threw = true;
    }
    CHECK(!threw);
    cpsl::radar::set_log_sink(nullptr);
}

TEST_CASE(radar_cfg_load_chatter_is_debug_only) {
    capture_sink();
    cpsl::radar::set_log_level(LogLevel::info);
    RadarConfigReader r(std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg");
    CHECK(r.initialized);
    CHECK(captured().lines.empty());
    cpsl::radar::set_log_level(LogLevel::debug);
    RadarConfigReader r2(std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg");
    CHECK_EQ(captured().lines.size(), size_t(1));
    CHECK(captured().lines[0].second.find("[RadarConfig] rx_antennas") == 0);
    cpsl::radar::set_log_level(LogLevel::info);
    cpsl::radar::set_log_sink(nullptr);
}

TEST_CASE(status_and_result) {
    using cpsl::radar::Code;
    using cpsl::radar::Result;
    using cpsl::radar::Status;
    CHECK(static_cast<bool>(Status::ok()));
    Status bad(Code::io_error, "gone");
    CHECK(!bad);
    CHECK(bad != Status::ok());
    CHECK_EQ(std::string(cpsl::radar::to_string(bad.code)), std::string("io_error"));
    Result<int> r(7);
    CHECK(static_cast<bool>(r));
    CHECK_EQ(*r, 7);
    Result<int> e(bad);
    CHECK(!e);
    CHECK(e.status == bad);
}

TEST_MAIN()
