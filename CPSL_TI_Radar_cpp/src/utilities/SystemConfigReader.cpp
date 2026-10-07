#include "SystemConfigReader.hpp"

#include <climits>
#include <cstdlib>
#include <fstream>
#include <set>
#include <sys/stat.h>

using json = nlohmann::json;

namespace {

// Defaults for optional v2 keys (design §2)
constexpr size_t kDefaultRcvbufBytes = 64u * 1024u * 1024u;
constexpr uint32_t kDefaultFrameQueueDepth = 4;
constexpr uint32_t kDefaultRxPriority = 0;
constexpr uint32_t kDefaultWorkerPriority = 0;

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
    firmware_id.clear();
    firmware = cpsl::radar::FirmwareDescriptor();
    firmware_path.clear();
    issues.clear();
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
    skip_configure = false;
    firmware_check = cpsl::radar::FirmwareCheck::automatic;
    rx_cpu = -1;
    worker_cpu = -1;
    rx_priority = kDefaultRxPriority;
    worker_priority = kDefaultWorkerPriority;
}

bool SystemConfigReader::initialize(const std::string& jsonFilePath) {
    reset();
    json_file_path = jsonFilePath;
    initialized = load();  // on failure the caller reports get_error()
    if (!initialized && issues.empty()) issues.push_back({"config_invalid", error, json_file_path});
    return initialized;
}

std::string SystemConfigReader::get_output_path(const std::string& name) const {
    return output_dir.empty() ? name : output_dir + "/" + name;
}

bool SystemConfigReader::load_issue(const std::string& code, const std::string& message,
                                    const std::string& source) {
    error = message;
    issues.push_back({code, message, source});
    return false;
}

// "firmware" checks (gui-04): descriptor exists and loads, the board lists it, the board name agrees with
// the descriptor's driver_board mapping, and the enabled streams are outputs of that firmware.
bool SystemConfigReader::check_firmware(const std::string& src, const std::string& board_dir) {
    using cpsl::radar::FirmwareDescriptor;
    const std::string where = src + ": /firmware: ";
    std::string supported;
    for (const std::string& f : board.firmwares) supported += (supported.empty() ? "" : ", ") + f;

    // the board's own list first: it names the fix
    if (!board.firmwares.empty()) {
        bool listed = false;
        for (const std::string& f : board.firmwares) listed = listed || f == firmware_id;
        if (!listed) {
            return load_issue("firmware_unsupported",
                              where + "firmware \"" + firmware_id + "\" is not supported by board " + board.name +
                                  ". Board " + board.name + " supports: " + supported + ".",
                              board_path);
        }
    }

    const char* env = std::getenv(kFirmwareDirEnv);
    const std::string fw_dir = (env != nullptr && *env != '\0') ? std::string(env) : board_dir + "/../firmware";
    firmware_path = fw_dir + "/" + firmware_id + ".json";
    if (!file_exists(firmware_path)) {
        return load_issue("firmware_unknown",
                          where + "no firmware descriptor \"" + firmware_id + "\" at " + firmware_path +
                              (supported.empty() ? "" : " (board " + board.name + " supports: " + supported + ")"),
                          firmware_path);
    }
    std::string fw_err;
    if (!FirmwareDescriptor::load(firmware_path, firmware, fw_err)) {
        return load_issue("firmware_descriptor", src + ": firmware: " + fw_err, firmware_path);
    }

    // The descriptor is keyed by the GUI board name; a system JSON names the driver board.
    const std::string gui_board = firmware.gui_board_for(board.name);
    if (!firmware.supports_board(gui_board)) {
        std::string boards;
        for (const auto& kv : firmware.templates) boards += (boards.empty() ? "" : ", ") + kv.first;
        return load_issue("firmware_board",
                          where + "firmware \"" + firmware_id + "\" has no support for board " + board.name +
                              " (its descriptor lists: " + boards + ")",
                          firmware_path);
    }
    const std::string driver_board = firmware.driver_board_for(gui_board);
    if (driver_board != board.name) {
        return load_issue("firmware_alias",
                          where + "firmware " + firmware_id + " on " + board.name + " runs with board " +
                              driver_board + " (descriptor driver_board); set \"board\": \"" + driver_board + "\"",
                          firmware_path);
    }

    // gui-33: a board that takes a cfg once per power-up must say whether querying it is safe
    {
        auto idn = firmware.identify.find(gui_board);
        if (idn != firmware.identify.end() && board.lifecycle.config_once_per_boot && !idn->second.has_once_safe) {
            return load_issue("firmware_descriptor",
                              src + ": firmware: " + firmware_path + ": /identify/" + gui_board +
                                  "/once_safe: missing required key (board " + board.name +
                                  " accepts a cfg once per power-up)",
                              firmware_path);
        }
    }
    const FirmwareDescriptor::Output& out = firmware.outputs.at(gui_board);
    if (serial_enabled && !out.tlv) {
        return load_issue("firmware_output_tlv",
                          where + "firmware " + firmware_id + " has no TLV output on " + board.name +
                              ": serial_stream.enabled is not allowed",
                          firmware_path);
    }
    if (dca_enabled && !out.lvds) {
        return load_issue("firmware_output_lvds",
                          where + "firmware " + firmware_id + " has no LVDS output on " + board.name +
                              ": dca1000.enabled is not allowed",
                          firmware_path);
    }
    return true;
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
                   "output", "runtime", "firmware"},
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

    // runtime: optional; every key is applied (rx_cpu, worker_cpu, rx_priority
    // and worker_priority since core-15: ThreadPlacement.hpp)
    if (data.contains("runtime")) {
        const json& rt = data.at("runtime");
        const std::string p = "/runtime";
        if (!r.object(rt, p,
                      {"log_level", "frame_queue_depth", "stall_timeout_ms", "rx_cpu", "worker_cpu", "rx_priority",
                       "worker_priority", "skip_configure", "firmware_check"})) {
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
        if (rt.contains("skip_configure") && !r.boolean(rt, "skip_configure", p, skip_configure)) return failed();
        if (rt.contains("firmware_check")) {
            std::string fc;
            if (!r.str(rt, "firmware_check", p, fc)) return failed();
            if (fc == "auto") firmware_check = cpsl::radar::FirmwareCheck::automatic;
            else if (fc == "warn") firmware_check = cpsl::radar::FirmwareCheck::warn;
            else if (fc == "off") firmware_check = cpsl::radar::FirmwareCheck::off;
            else {
                r.fail(p + "/firmware_check", "\"" + fc + "\" is not one of: auto, warn, off");
                return failed();
            }
        }
        if (rt.contains("rx_cpu") && !r.cpu(rt, "rx_cpu", p, rx_cpu)) return failed();
        if (rt.contains("worker_cpu") && !r.cpu(rt, "worker_cpu", p, worker_cpu)) return failed();
        if (rt.contains("rx_priority")) {
            if (!r.uint(rt, "rx_priority", p, 0, 99, x)) return failed();
            rx_priority = static_cast<uint32_t>(x);
        }
        if (rt.contains("worker_priority")) {
            if (!r.uint(rt, "worker_priority", p, 0, 99, x)) return failed();
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

    // The firmware decides the cfg command rules (skip/required/forbidden) and the CLI prompt (gui-33 Step 4).
    // A board_overrides "cli.prompt" still wins over the firmware's.
    const bool keep_prompt = overrides != nullptr && overrides->contains("cli") && overrides->at("cli").is_object() &&
                             overrides->at("cli").contains("prompt");
    if (data.contains("firmware")) {
        if (!r.str(data, "firmware", "", firmware_id)) return failed();
        if (!check_firmware(src, dir_of(board_path))) return false;
        std::string apply_err;
        if (!cpsl::radar::apply_firmware_to_board(firmware, firmware_path, keep_prompt, board, apply_err)) {
            return load_issue("firmware_descriptor", src + ": firmware: " + apply_err, firmware_path);
        }
    } else {
        // No "firmware" key (optional until gui-04 Step 3a): the board's default firmware (first of its
        // "firmwares" list) supplies the rules. A missing descriptor file means no rules (custom board dirs);
        // a descriptor that exists must load.
        const std::string def_id = cpsl::radar::default_firmware_id(board);
        if (!def_id.empty()) {
            const char* env = std::getenv(kFirmwareDirEnv);
            const std::string fw_dir =
                (env != nullptr && *env != '\0') ? std::string(env) : dir_of(board_path) + "/../firmware";
            const std::string def_path = fw_dir + "/" + def_id + ".json";
            if (file_exists(def_path)) {
                cpsl::radar::FirmwareDescriptor def_fw;
                std::string fw_err;
                if (!cpsl::radar::FirmwareDescriptor::load(def_path, def_fw, fw_err)) {
                    return load_issue("firmware_descriptor", src + ": default firmware " + def_id + ": " + fw_err,
                                      def_path);
                }
                if (!cpsl::radar::apply_firmware_to_board(def_fw, def_path, keep_prompt, board, fw_err)) {
                    return load_issue("firmware_descriptor", src + ": default firmware " + def_id + ": " + fw_err,
                                      def_path);
                }
            }
        }
    }

    // radar cfg vs board, for the enabled streams
    cpsl::radar::StreamSelection streams;
    streams.dca1000 = dca_enabled;
    streams.serial = serial_enabled;
    cpsl::radar::CfgCheckResult chk = cpsl::radar::cross_check_radar_cfg(board, radar_cfg_path, streams);
    cfg_notes = chk.notes;
    if (!chk.ok()) {
        error = src + ": radar cfg does not fit board " + board.name + ":";
        for (const std::string& e : chk.errors) {
            error += "\n  " + e;
            issues.push_back({"radar_cfg", e, radar_cfg_path});
        }
        return false;
    }

    return true;
}
