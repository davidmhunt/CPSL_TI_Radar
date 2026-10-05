// RadarConfig::load and output.dir handling (directive core-13 Step 2;
// core-10 review S3: a config could validate but fail at run time because
// output.dir did not exist).
#include "test_harness.hpp"
#include "RadarConfig.hpp"

#include <sys/stat.h>
#include <unistd.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>

using cpsl::radar::Code;
using cpsl::radar::OutputDirCheck;
using cpsl::radar::RadarConfig;

static const std::string kTmp = std::string(TEST_TMP_DIR) + "/radar_config";
static const bool kSetup = [] {
    setenv(SystemConfigReader::kBoardsDirEnv, (std::string(CONFIG_DIR) + "/boards").c_str(), 1);
    std::filesystem::remove_all(kTmp);
    std::filesystem::create_directories(kTmp);
    return true;
}();

static bool has(const std::string& s, const std::string& sub) { return s.find(sub) != std::string::npos; }

static json base_config() {
    json j = json::parse(R"({
        "schema_version": 2,
        "board": "IWR1843",
        "radar_cfg": "",
        "cli": { "port": "/dev/null-not-opened" },
        "dca1000": { "enabled": true, "fpga_ip": "127.0.0.1", "host_ip": "127.0.0.1",
                     "cmd_port": 4096, "data_port": 4098 },
        "output": { "save_adc_frames": true }
    })");
    j["radar_cfg"] = std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg";
    return j;
}

static std::string write(const std::string& name, const std::string& text) {
    const std::string p = kTmp + "/" + name;
    std::ofstream(p) << text;
    return p;
}

TEST_CASE(loads_a_valid_config) {
    auto r = RadarConfig::load(write("ok.json", base_config().dump()));
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK_EQ(r->board().name, std::string("IWR1843"));
    CHECK_EQ(r->frame_shape().rx, 4u);
    CHECK_EQ(r->frame_shape().samples, 63u);
    CHECK_EQ(r->frame_shape().chirps, 230u);
    CHECK_EQ(r->frame_shape().bytes, uint64_t(4) * 4 * 63 * 230);
    CHECK_NEAR(r->frame_shape().period_ms, 100.0, 1e-6);
    CHECK(!r->commands().send.empty());
    CHECK(r->output_dir_check().state == OutputDirCheck::State::current_dir);
}

TEST_CASE(errors_are_statuses_not_exceptions) {
    auto missing = RadarConfig::load(kTmp + "/does_not_exist.json");
    CHECK(!missing);
    CHECK(missing.status.code == Code::invalid_config);
    CHECK(has(missing.status.message, "does_not_exist.json"));

    auto garbage = RadarConfig::load(write("garbage.json", "{ not json"));
    CHECK(!garbage);
    CHECK(garbage.status.code == Code::invalid_config);

    json v1 = json::parse(R"({"verbose": true})");
    auto old = RadarConfig::load(write("v1.json", v1.dump()));
    CHECK(!old);
    CHECK(has(old.status.message, "tools/migrate_config_v1_to_v2.py"));

    json bad_cfg = base_config();
    bad_cfg["radar_cfg"] = std::string(TEST_DATA_DIR) + "/radar/short_profilecfg.cfg";
    auto b = RadarConfig::load(write("bad_cfg.json", bad_cfg.dump()));
    CHECK(!b);
    CHECK(has(b.status.message, "short_profilecfg.cfg"));
}

TEST_CASE(output_dir_states) {
    // exists
    const std::string existing = kTmp + "/existing";
    std::filesystem::create_directories(existing);
    CHECK(cpsl::radar::check_output_dir(existing).state == OutputDirCheck::State::exists);
    // will be created (two missing levels)
    CHECK(cpsl::radar::check_output_dir(existing + "/a/b").state == OutputDirCheck::State::will_be_created);
    // relative path, resolved against the JSON file like the driver does
    json j = base_config();
    j["output"]["dir"] = "rel_out/run1";
    auto r = RadarConfig::load(write("rel.json", j.dump()));
    CHECK(static_cast<bool>(r));
    if (r) {
        const OutputDirCheck c = r->output_dir_check();
        CHECK(c.state == OutputDirCheck::State::will_be_created);
        CHECK(has(c.path, "rel_out/run1"));
    }
}

TEST_CASE(output_dir_under_a_regular_file_is_an_error_naming_it) {
    const std::string file = write("a_file", "x");
    const OutputDirCheck c = cpsl::radar::check_output_dir(file + "/sub/dir");
    CHECK(c.state == OutputDirCheck::State::error);
    CHECK(has(c.message, file + "/sub/dir"));
    CHECK(has(c.message, file + " is a file"));
    // the directory itself being a file
    const OutputDirCheck d = cpsl::radar::check_output_dir(file);
    CHECK(d.state == OutputDirCheck::State::error);
    CHECK(has(d.message, file));
    // creating it fails with a Status naming the path
    const cpsl::radar::Status s = cpsl::radar::create_output_dir(file + "/sub");
    CHECK(s.code == Code::output_dir);
    CHECK(has(s.message, file + "/sub"));
}

TEST_CASE(output_dir_with_a_read_only_parent_is_an_error) {
    if (geteuid() == 0) return;  // root writes anywhere
    const std::string ro = kTmp + "/read_only";
    std::filesystem::create_directories(ro);
    chmod(ro.c_str(), 0555);
    const OutputDirCheck c = cpsl::radar::check_output_dir(ro + "/new");
    CHECK(c.state == OutputDirCheck::State::error);
    CHECK(has(c.message, ro + " is not writable"));
    chmod(ro.c_str(), 0755);
}

TEST_CASE(create_output_dir_makes_parents) {
    const std::string d = kTmp + "/made/x/y";
    CHECK(static_cast<bool>(cpsl::radar::create_output_dir(d)));
    CHECK(std::filesystem::is_directory(d));
    CHECK(static_cast<bool>(cpsl::radar::create_output_dir(d)));  // already there: ok
    CHECK(static_cast<bool>(cpsl::radar::create_output_dir("")));  // unset: nothing to do
}

TEST_MAIN()
