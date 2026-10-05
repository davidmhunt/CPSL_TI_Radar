#include "SystemConfigReader.hpp"

#include <climits>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <set>
#include <sys/stat.h>

using json = nlohmann::json;

const char* to_string(LogLevel v) {
    switch (v) {
        case LogLevel::error: return "error";
        case LogLevel::warn: return "warn";
        case LogLevel::info: return "info";
        case LogLevel::debug: return "debug";
    }
    return "?";
}

namespace {

// Defaults for optional v2 keys (design §2)
constexpr size_t kDefaultRcvbufBytes = 64u * 1024u * 1024u;
constexpr uint32_t kDefaultFrameQueueDepth = 4;
constexpr uint32_t kDefaultRxPriority = 99;
constexpr uint32_t kDefaultWorkerPriority = 80;

std::string dir_of(const std::string& path) {
    size_t pos = path.find_last_of('/');
    if (pos == std::string::npos) return ".";
    if (pos == 0) return "/";
    return path.substr(0, pos);
}

// Relative paths resolve against the JSON file's directory.
std::string resolve(const std::string& json_path, const std::string& p) {
    if (p.empty() || p[0] == '/') return p;
    return dir_of(json_path) + "/" + p;
}

bool file_exists(const std::string& p) {
    struct stat st;
    return stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

// Strict reads: each returns false after writing "<path>: <problem>" to err.
class V2Reader {
public:
    explicit V2Reader(std::string& err) : err_(err) {}

    bool fail(const std::string& path, const std::string& msg) {
        err_ = (path.empty() ? "/" : path) + ": " + msg;
        return false;
    }

    bool object(const json& j, const std::string& path, const std::set<std::string>& allowed,
                const std::set<std::string>& required = {}) {
        if (!j.is_object()) return fail(path, "expected an object");
        for (auto it = j.begin(); it != j.end(); ++it) {
            if (!allowed.count(it.key())) {
                std::string list;
                for (const auto& k : allowed) list += (list.empty() ? "" : ", ") + k;
                return fail(path + "/" + it.key(), "unknown key (allowed: " + list + ")");
            }
        }
        for (const auto& k : required) {
            if (!j.contains(k)) return fail(path + "/" + k, "missing required key");
        }
        return true;
    }

    bool str(const json& j, const std::string& key, const std::string& path, std::string& out) {
        const json& v = j.at(key);
        if (!v.is_string()) return fail(path + "/" + key, "expected a string");
        out = v.get<std::string>();
        if (out.empty()) return fail(path + "/" + key, "must not be empty");
        return true;
    }

    bool boolean(const json& j, const std::string& key, const std::string& path, bool& out) {
        const json& v = j.at(key);
        if (!v.is_boolean()) return fail(path + "/" + key, "expected true or false");
        out = v.get<bool>();
        return true;
    }

    bool uint(const json& j, const std::string& key, const std::string& path, uint64_t min, uint64_t max,
              uint64_t& out) {
        const json& v = j.at(key);
        const std::string p = path + "/" + key;
        if (!v.is_number_integer()) return fail(p, "expected an integer");
        if (!v.is_number_unsigned() && v.get<int64_t>() < 0) return fail(p, "must not be negative");
        uint64_t x = v.get<uint64_t>();
        if (x < min || x > max) {
            return fail(p, std::to_string(x) + " is outside [" + std::to_string(min) + ", " + std::to_string(max) +
                               "]");
        }
        out = x;
        return true;
    }

    // integer in range, or null (stored as -1)
    bool cpu(const json& j, const std::string& key, const std::string& path, int& out) {
        if (j.at(key).is_null()) {
            out = -1;
            return true;
        }
        uint64_t x = 0;
        if (!uint(j, key, path, 0, 1023, x)) return false;
        out = static_cast<int>(x);
        return true;
    }

private:
    std::string& err_;
};

}  // namespace

SystemConfigReader::SystemConfigReader() { reset(); }

SystemConfigReader::SystemConfigReader(const std::string& jsonFilePath) {
    reset();
    initialize(jsonFilePath);
}

void SystemConfigReader::reset() {
    initialized = false;
    error.clear();
    board = cpsl::radar::BoardDescriptor();
    board_path.clear();
    cfg_notes.clear();
    radar_cfg_path.clear();
    cli_port.clear();
    serial_enabled = false;
    serial_port.clear();
    dca_enabled = false;
    dca_fpga_ip.clear();
    dca_host_ip.clear();
    dca_cmd_port = 0;
    dca_data_port = 0;
    dca_rcvbuf_bytes = kDefaultRcvbufBytes;
    output_dir.clear();
    save_adc_frames = false;
    save_raw_lvds = false;
    log_level = LogLevel::info;
    frame_queue_depth = kDefaultFrameQueueDepth;
    stall_timeout_ms = 0;
    rx_cpu = -1;
    worker_cpu = -1;
    rx_priority = kDefaultRxPriority;
    worker_priority = kDefaultWorkerPriority;
}

bool SystemConfigReader::initialize(const std::string& jsonFilePath) {
    reset();
    json_file_path = jsonFilePath;
    initialized = load();
    if (!initialized) {
        std::cerr << "SystemConfigReader: " << error << std::endl;
    }
    return initialized;
}

std::string SystemConfigReader::get_output_path(const std::string& name) const {
    return output_dir.empty() ? name : output_dir + "/" + name;
}

bool SystemConfigReader::load() {
    const std::string& src = json_file_path;

    std::ifstream file(src);
    if (!file.is_open()) {
        error = src + ": cannot open system config";
        return false;
    }
    json data;
    if (!cpsl::radar::parse_json_strict(file, src, data, error)) return false;

    std::string err;
    V2Reader r(err);
    auto failed = [&]() {
        error = src + ": " + err;
        return false;
    };

    if (!data.is_object()) {
        r.fail("", "expected a JSON object");
        return failed();
    }

    // schema_version: v1 files have none (design D8: hard error, no dual reading)
    if (!data.contains("schema_version")) {
        error = src + ": this is a v1 system config (no \"schema_version\"). The driver reads schema " +
                std::to_string(kSchemaVersion) + " only; convert it with: uv run " + kMigrationScript + " --in-place " +
                src;
        return false;
    }
    {
        const json& v = data.at("schema_version");
        if (!v.is_number_integer() || v.get<int64_t>() != kSchemaVersion) {
            r.fail("/schema_version", "unsupported schema_version " + v.dump() + " (this driver reads " +
                                          std::to_string(kSchemaVersion) + ")");
            return failed();
        }
    }

    if (!r.object(data, "",
                  {"schema_version", "board", "board_overrides", "radar_cfg", "cli", "serial_stream", "dca1000",
                   "output", "runtime"},
                  {"board", "radar_cfg", "cli"})) {
        return failed();
    }

    // radar_cfg
    std::string radar_cfg;
    if (!r.str(data, "radar_cfg", "", radar_cfg)) return failed();
    radar_cfg_path = resolve(src, radar_cfg);

    // cli
    {
        const json& c = data.at("cli");
        if (!r.object(c, "/cli", {"port"}, {"port"}) || !r.str(c, "port", "/cli", cli_port)) return failed();
    }

    // serial_stream: optional; port required when enabled
    if (data.contains("serial_stream")) {
        const json& s = data.at("serial_stream");
        const std::string p = "/serial_stream";
        if (!r.object(s, p, {"enabled", "port"}, {"enabled"}) || !r.boolean(s, "enabled", p, serial_enabled)) {
            return failed();
        }
        if (s.contains("port")) {
            if (!r.str(s, "port", p, serial_port)) return failed();
        } else if (serial_enabled) {
            r.fail(p + "/port", "required when serial_stream.enabled is true");
            return failed();
        }
    }

    // dca1000: optional; addresses and ports required when enabled
    if (data.contains("dca1000")) {
        const json& d = data.at("dca1000");
        const std::string p = "/dca1000";
        if (!r.object(d, p, {"enabled", "fpga_ip", "host_ip", "cmd_port", "data_port", "rcvbuf_bytes"},
                      {"enabled"}) ||
            !r.boolean(d, "enabled", p, dca_enabled)) {
            return failed();
        }
        for (const char* k : {"fpga_ip", "host_ip", "cmd_port", "data_port"}) {
            if (dca_enabled && !d.contains(k)) {
                r.fail(p + "/" + k, "required when dca1000.enabled is true");
                return failed();
            }
        }
        uint64_t x = 0;
        if (d.contains("fpga_ip") && !r.str(d, "fpga_ip", p, dca_fpga_ip)) return failed();
        if (d.contains("host_ip") && !r.str(d, "host_ip", p, dca_host_ip)) return failed();
        if (d.contains("cmd_port")) {
            if (!r.uint(d, "cmd_port", p, 1, 65535, x)) return failed();
            dca_cmd_port = static_cast<int>(x);
        }
        if (d.contains("data_port")) {
            if (!r.uint(d, "data_port", p, 1, 65535, x)) return failed();
            dca_data_port = static_cast<int>(x);
        }
        if (d.contains("rcvbuf_bytes")) {
            if (!r.uint(d, "rcvbuf_bytes", p, 1, INT_MAX, x)) return failed();
            dca_rcvbuf_bytes = static_cast<size_t>(x);
        }
    }

    if (!serial_enabled && !dca_enabled) {
        error = src + ": neither serial_stream nor dca1000 is enabled: nothing to stream";
        return false;
    }

    // output: optional
    if (data.contains("output")) {
        const json& o = data.at("output");
        const std::string p = "/output";
        if (!r.object(o, p, {"dir", "save_adc_frames", "save_raw_lvds"})) return failed();
        if (o.contains("dir")) {
            std::string dir;
            if (!r.str(o, "dir", p, dir)) return failed();
            output_dir = resolve(src, dir);
        }
        if (o.contains("save_adc_frames") && !r.boolean(o, "save_adc_frames", p, save_adc_frames)) return failed();
        if (o.contains("save_raw_lvds") && !r.boolean(o, "save_raw_lvds", p, save_raw_lvds)) return failed();
    }

    // runtime: optional; everything but log_level is reserved (validated, not applied yet)
    if (data.contains("runtime")) {
        const json& rt = data.at("runtime");
        const std::string p = "/runtime";
        if (!r.object(rt, p,
                      {"log_level", "frame_queue_depth", "stall_timeout_ms", "rx_cpu", "worker_cpu", "rx_priority",
                       "worker_priority"})) {
            return failed();
        }
        if (rt.contains("log_level")) {
            std::string lv;
            if (!r.str(rt, "log_level", p, lv)) return failed();
            if (lv == "error") log_level = LogLevel::error;
            else if (lv == "warn") log_level = LogLevel::warn;
            else if (lv == "info") log_level = LogLevel::info;
            else if (lv == "debug") log_level = LogLevel::debug;
            else {
                r.fail(p + "/log_level", "\"" + lv + "\" is not one of: error, warn, info, debug");
                return failed();
            }
        }
        uint64_t x = 0;
        if (rt.contains("frame_queue_depth")) {
            if (!r.uint(rt, "frame_queue_depth", p, 1, 1024, x)) return failed();
            frame_queue_depth = static_cast<uint32_t>(x);
        }
        if (rt.contains("stall_timeout_ms")) {
            if (!r.uint(rt, "stall_timeout_ms", p, 0, 3600000, x)) return failed();
            stall_timeout_ms = static_cast<uint32_t>(x);
        }
        if (rt.contains("rx_cpu") && !r.cpu(rt, "rx_cpu", p, rx_cpu)) return failed();
        if (rt.contains("worker_cpu") && !r.cpu(rt, "worker_cpu", p, worker_cpu)) return failed();
        if (rt.contains("rx_priority")) {
            if (!r.uint(rt, "rx_priority", p, 1, 99, x)) return failed();
            rx_priority = static_cast<uint32_t>(x);
        }
        if (rt.contains("worker_priority")) {
            if (!r.uint(rt, "worker_priority", p, 1, 99, x)) return failed();
            worker_priority = static_cast<uint32_t>(x);
        }
    }

    // board (+ board_overrides): a plain name, or a path to a descriptor file
    std::string board_ref;
    if (!r.str(data, "board", "", board_ref)) return failed();
    const json* overrides = nullptr;
    if (data.contains("board_overrides")) {
        overrides = &data.at("board_overrides");
        if (!overrides->is_object()) {
            r.fail("/board_overrides", "expected an object");
            return failed();
        }
    }
    const bool is_path = board_ref.find('/') != std::string::npos ||
                         (board_ref.size() > 5 && board_ref.compare(board_ref.size() - 5, 5, ".json") == 0);
    if (is_path) {
        board_path = resolve(src, board_ref);
    } else {
        const char* env = std::getenv(kBoardsDirEnv);
        const std::string boards_dir = (env != nullptr && *env != '\0') ? std::string(env) : dir_of(src) + "/../boards";
        board_path = boards_dir + "/" + board_ref + ".json";
        if (!file_exists(board_path)) {
            error = src + ": /board: no descriptor \"" + board_ref + "\" at " + board_path +
                    " (set \"board\" to a descriptor path, or set " + kBoardsDirEnv + ")";
            return false;
        }
    }
    std::string board_err;
    if (!cpsl::radar::BoardDescriptor::load(board_path, board, board_err, overrides)) {
        error = src + ": board: " + board_err;
        return false;
    }

    // radar cfg vs board, for the enabled streams
    cpsl::radar::StreamSelection streams;
    streams.dca1000 = dca_enabled;
    streams.serial = serial_enabled;
    cpsl::radar::CfgCheckResult chk = cpsl::radar::cross_check_radar_cfg(board, radar_cfg_path, streams);
    cfg_notes = chk.notes;
    if (!chk.ok()) {
        error = src + ": radar cfg does not fit board " + board.name + ":";
        for (const std::string& e : chk.errors) error += "\n  " + e;
        return false;
    }

    return true;
}
