#include "BoardDescriptor.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <fstream>
#include <set>
#include <sstream>
#include <utility>

using nlohmann::json;

namespace cpsl {
namespace radar {

const char* to_string(Sdk v) {
    switch (v) {
        case Sdk::mmwave_sdk_2: return "mmwave_sdk_2";
        case Sdk::mmwave_sdk_3: return "mmwave_sdk_3";
        case Sdk::mmwave_mcuplus: return "mmwave_mcuplus";
    }
    return "?";
}
const char* to_string(TlvDialect v) {
    switch (v) {
        case TlvDialect::sdk3: return "sdk3";
        case TlvDialect::sdk2: return "sdk2";
        case TlvDialect::mcuplus_cascade: return "mcuplus_cascade";
    }
    return "?";
}
const char* to_string(LvdsLayout v) {
    switch (v) {
        case LvdsLayout::two_lane_iq_pairs: return "two_lane_iq_pairs";
        case LvdsLayout::lane_per_rx: return "lane_per_rx";
    }
    return "?";
}
const char* to_string(IqOrder v) {
    switch (v) {
        case IqOrder::i_first: return "i_first";
        case IqOrder::q_first: return "q_first";
    }
    return "?";
}

namespace {

// ---------------------------------------------------------------------------
// Strict JSON reading. Every reader returns false after writing one message
// "<source>: <json path>: <problem>" into err.
// ---------------------------------------------------------------------------
class Reader {
public:
    Reader(const std::string& source, std::string& err) : source_(source), err_(err) {}

    bool fail(const std::string& path, const std::string& msg) {
        err_ = source_ + ": " + (path.empty() ? "/" : path) + ": " + msg;
        return false;
    }

    // `j` must be an object with every key in `required`, and no key outside
    // required + optional.
    bool object(const json& j, const std::string& path, const std::set<std::string>& required,
                const std::set<std::string>& optional = {}) {
        if (!j.is_object()) return fail(path, "expected an object");
        for (auto it = j.begin(); it != j.end(); ++it) {
            if (!required.count(it.key()) && !optional.count(it.key())) {
                return fail(path + "/" + it.key(), "unknown key (allowed: " + list(required, optional) + ")");
            }
        }
        for (const std::string& k : required) {
            if (!j.contains(k)) return fail(path + "/" + k, "missing required key");
        }
        return true;
    }

    bool uint(const json& j, const std::string& key, const std::string& path, uint64_t min, uint64_t max,
              uint32_t& out) {
        return uint_value(j.at(key), path + "/" + key, min, max, out);
    }

    bool uint_value(const json& v, const std::string& p, uint64_t min, uint64_t max, uint32_t& out) {
        if (!v.is_number_integer()) return fail(p, "expected an integer");
        if (!v.is_number_unsigned() && v.get<int64_t>() < 0) return fail(p, "must not be negative");
        uint64_t x = v.get<uint64_t>();
        if (x < min || x > max) {
            return fail(p, std::to_string(x) + " is outside [" + std::to_string(min) + ", " +
                               std::to_string(max) + "]");
        }
        out = static_cast<uint32_t>(x);
        return true;
    }

    bool boolean(const json& j, const std::string& key, const std::string& path, bool& out) {
        const json& v = j.at(key);
        if (!v.is_boolean()) return fail(path + "/" + key, "expected true or false");
        out = v.get<bool>();
        return true;
    }

    bool str(const json& j, const std::string& key, const std::string& path, std::string& out) {
        const json& v = j.at(key);
        if (!v.is_string()) return fail(path + "/" + key, "expected a string");
        out = v.get<std::string>();
        if (out.empty()) return fail(path + "/" + key, "must not be empty");
        return true;
    }

    bool str_array(const json& j, const std::string& key, const std::string& path,
                   std::vector<std::string>& out) {
        const json& v = j.at(key);
        const std::string p = path + "/" + key;
        if (!v.is_array() || v.empty()) return fail(p, "expected a non-empty array of strings");
        out.clear();
        for (size_t i = 0; i < v.size(); i++) {
            if (!v[i].is_string() || v[i].get<std::string>().empty()) {
                return fail(p + "/" + std::to_string(i), "expected a non-empty string");
            }
            out.push_back(v[i].get<std::string>());
        }
        return true;
    }

    bool uint_array(const json& j, const std::string& key, const std::string& path, uint32_t min,
                    uint32_t max, std::vector<uint32_t>& out) {
        const json& v = j.at(key);
        const std::string p = path + "/" + key;
        if (!v.is_array() || v.empty()) return fail(p, "expected a non-empty array of integers");
        out.clear();
        for (size_t i = 0; i < v.size(); i++) {
            uint32_t x = 0;
            if (!uint_value(v[i], p + "/" + std::to_string(i), min, max, x)) return false;
            out.push_back(x);
        }
        return true;
    }

    template <class E>
    bool enumeration(const json& j, const std::string& key, const std::string& path,
                     const std::vector<std::pair<const char*, E>>& table, E& out) {
        const json& v = j.at(key);
        const std::string p = path + "/" + key;
        std::string allowed;
        for (const auto& e : table) allowed += (allowed.empty() ? "" : ", ") + std::string(e.first);
        if (!v.is_string()) return fail(p, "expected a string, one of: " + allowed);
        const std::string s = v.get<std::string>();
        for (const auto& e : table) {
            if (s == e.first) {
                out = e.second;
                return true;
            }
        }
        return fail(p, "\"" + s + "\" is not one of: " + allowed);
    }

private:
    static std::string list(const std::set<std::string>& a, const std::set<std::string>& b) {
        std::string s;
        for (const auto& k : a) s += (s.empty() ? "" : ", ") + k;
        for (const auto& k : b) s += (s.empty() ? "" : ", ") + k;
        return s;
    }

    std::string source_;
    std::string& err_;
};

std::string file_stem(const std::string& path) {
    std::string::size_type slash = path.find_last_of('/');
    std::string base = slash == std::string::npos ? path : path.substr(slash + 1);
    std::string::size_type dot = base.rfind('.');
    return dot == std::string::npos ? base : base.substr(0, dot);
}

}  // namespace

bool BoardDescriptor::from_json(const json& j, const std::string& expected_name, const std::string& source,
                                BoardDescriptor& out, std::string& error) {
    Reader r(source, error);
    BoardDescriptor d;

    if (!r.object(j, "", {"schema", "name", "sdk", "cli", "lifecycle", "cfg_dialect", "data_uart", "lvds"},
                  {"dca1000", "firmwares", "elevation_tx_bit"})) {   // "elevation_tx_bit": host-GUI metadata (radar_gui/cfg/), not read by the driver
        return false;
    }

    // schema
    {
        const json& v = j.at("schema");
        if (!v.is_number_integer() || v.get<int64_t>() != kSchema) {
            return r.fail("/schema", "unsupported schema " + v.dump() + " (this driver reads schema " +
                                         std::to_string(kSchema) + ")");
        }
        d.schema = kSchema;
    }

    if (!r.str(j, "name", "", d.name)) return false;
    if (!expected_name.empty() && d.name != expected_name) {
        return r.fail("/name", "\"" + d.name + "\" must match the file name \"" + expected_name + "\"");
    }

    if (!r.enumeration<Sdk>(j, "sdk", "",
                            {{"mmwave_sdk_2", Sdk::mmwave_sdk_2},
                             {"mmwave_sdk_3", Sdk::mmwave_sdk_3},
                             {"mmwave_mcuplus", Sdk::mmwave_mcuplus}},
                            d.sdk)) {
        return false;
    }

    // cli
    {
        const json& c = j.at("cli");
        const std::string p = "/cli";
        if (!r.object(c, p, {"baud", "ack", "error_tokens", "prompt", "prompt_wait_ms", "cmd_timeout_ms",
                             "start_cmd", "stop_cmd", "skip_prefixes"},
                      {"stop_timeout_ms"})) {
            return false;
        }
        // stop_timeout_ms: optional; null or absent = computed from the frame period
        if (c.contains("stop_timeout_ms") && !c.at("stop_timeout_ms").is_null() &&
            !r.uint(c, "stop_timeout_ms", p, 1, 600000, d.cli.stop_timeout_ms)) {
            return false;
        }
        if (!r.uint(c, "baud", p, 1, 0xFFFFFFFFu, d.cli.baud) || !r.str(c, "ack", p, d.cli.ack) ||
            !r.str_array(c, "error_tokens", p, d.cli.error_tokens) || !r.str(c, "prompt", p, d.cli.prompt) ||
            !r.uint(c, "prompt_wait_ms", p, 0, 600000, d.cli.prompt_wait_ms) ||
            !r.uint(c, "cmd_timeout_ms", p, 1, 600000, d.cli.cmd_timeout_ms) ||
            !r.str(c, "start_cmd", p, d.cli.start_cmd) || !r.str(c, "stop_cmd", p, d.cli.stop_cmd) ||
            !r.str_array(c, "skip_prefixes", p, d.cli.skip_prefixes)) {
            return false;
        }
    }

    // lifecycle
    {
        const json& l = j.at("lifecycle");
        if (!r.object(l, "/lifecycle", {"config_once_per_boot"}) ||
            !r.boolean(l, "config_once_per_boot", "/lifecycle", d.lifecycle.config_once_per_boot)) {
            return false;
        }
    }

    // cfg_dialect: field indices count the command word as field 0
    {
        const json& c = j.at("cfg_dialect");
        const std::string p = "/cfg_dialect";
        // skip_commands / required_commands / forbidden_commands moved to the firmware descriptor (gui-33 Step 4):
        // they depend on the image, not the silicon. Say where they went instead of "unknown key".
        if (c.is_object()) {
            for (const char* moved : {"skip_commands", "required_commands", "forbidden_commands"}) {
                if (c.contains(moved)) {
                    return r.fail(p + "/" + moved,
                                  "moved to the firmware descriptor: set cfg_rules.<board>." + std::string(moved) +
                                      " in config/firmware/<firmware>.json");
                }
            }
        }
        if (!r.object(c, p, {"rx_mask_fields", "frame_period_field"}) ||
            !r.uint_array(c, "rx_mask_fields", p, 1, 64, d.cfg_dialect.rx_mask_fields) ||
            !r.uint(c, "frame_period_field", p, 1, 64, d.cfg_dialect.frame_period_field)) {
            return false;
        }
    }

    // data_uart
    {
        const json& u = j.at("data_uart");
        const std::string p = "/data_uart";
        if (u.is_object() && u.contains("supported")) {
            if (!r.boolean(u, "supported", p, d.data_uart.supported)) return false;
        }
        if (!d.data_uart.supported) {
            // no data UART: nothing else may be given
            if (!r.object(u, p, {"supported"})) return false;
        } else {
        if (!r.object(u, p, {"baud", "header_bytes", "tlv_dialect", "timeout_ms"}, {"supported"}) ||
            !r.uint(u, "baud", p, 1, 0xFFFFFFFFu, d.data_uart.baud) ||
            !r.uint(u, "header_bytes", p, 8, 4096, d.data_uart.header_bytes) ||
            !r.enumeration<TlvDialect>(u, "tlv_dialect", p,
                                       {{"sdk3", TlvDialect::sdk3},
                                        {"sdk2", TlvDialect::sdk2},
                                        {"mcuplus_cascade", TlvDialect::mcuplus_cascade}},
                                       d.data_uart.tlv_dialect) ||
            !r.uint(u, "timeout_ms", p, 1, 600000, d.data_uart.timeout_ms)) {
            return false;
        }
        // the header length follows from the dialect: SDK 2 has no subFrameNumber
        const uint32_t want = d.data_uart.tlv_dialect == TlvDialect::sdk2 ? 36u : 40u;
        if (d.data_uart.header_bytes != want) {
            return r.fail(p + "/header_bytes", "must be " + std::to_string(want) + " for tlv_dialect " +
                                                   to_string(d.data_uart.tlv_dialect) +
                                                   " (36 for sdk2, 40 for sdk3 and mcuplus_cascade)");
        }
        }
    }

    // lvds: {"supported": false} alone, or the full block
    {
        const json& l = j.at("lvds");
        const std::string p = "/lvds";
        if (!l.is_object()) return r.fail(p, "expected an object");
        if (!l.contains("supported")) return r.fail(p + "/supported", "missing required key");
        if (!r.boolean(l, "supported", p, d.lvds.supported)) return false;
        if (d.lvds.supported) {
            if (!r.object(l, p, {"supported", "lanes", "layout", "iq_order"})) return false;
            if (!r.uint(l, "lanes", p, 1, 8, d.lvds.lanes)) return false;
            if (d.lvds.lanes != 2 && d.lvds.lanes != 4) {
                return r.fail(p + "/lanes", std::to_string(d.lvds.lanes) + " is not one of: 2, 4");
            }
            if (!r.enumeration<LvdsLayout>(l, "layout", p,
                                           {{"two_lane_iq_pairs", LvdsLayout::two_lane_iq_pairs},
                                            {"lane_per_rx", LvdsLayout::lane_per_rx}},
                                           d.lvds.layout) ||
                !r.enumeration<IqOrder>(l, "iq_order", p,
                                        {{"i_first", IqOrder::i_first}, {"q_first", IqOrder::q_first}},
                                        d.lvds.iq_order)) {
                return false;
            }
            // SWRA581B: the 2-lane format pairs I/Q across lanes; the 4-lane
            // format carries one Rx per lane.
            const uint32_t layout_lanes = d.lvds.layout == LvdsLayout::two_lane_iq_pairs ? 2 : 4;
            if (d.lvds.lanes != layout_lanes) {
                return r.fail(p, std::string("layout ") + to_string(d.lvds.layout) + " needs lanes " +
                                     std::to_string(layout_lanes) + ", got " + std::to_string(d.lvds.lanes));
            }
        } else if (!r.object(l, p, {"supported"})) {
            return false;
        }
    }

    // firmwares: optional list of firmware descriptor ids
    if (j.contains("firmwares")) {
        const json& v = j.at("firmwares");
        if (!v.is_array() || v.empty()) return r.fail("/firmwares", "expected a non-empty array of firmware ids");
        std::set<std::string> seen;
        for (size_t i = 0; i < v.size(); i++) {
            const std::string ip = "/firmwares/" + std::to_string(i);
            if (!v[i].is_string() || v[i].get<std::string>().empty()) return r.fail(ip, "expected a non-empty string");
            const std::string id = v[i].get<std::string>();
            if (!seen.insert(id).second) return r.fail(ip, "\"" + id + "\" is listed twice");
            d.firmwares.push_back(id);
        }
    }

    // dca1000: required with LVDS, forbidden without it
    if (d.lvds.supported) {
        if (!j.contains("dca1000")) return r.fail("/dca1000", "required when lvds.supported is true");
        const json& c = j.at("dca1000");
        const std::string p = "/dca1000";
        // packet_bytes: DCA1000 UDP datagram, 10-byte header + payload, at most 1472
        // fpga_timer_s: one byte of CONFIG_FPGA_GEN
        if (!r.object(c, p, {"packet_bytes", "packet_delay_us", "fpga_timer_s"}) ||
            !r.uint(c, "packet_bytes", p, 11, 1472, d.dca1000.packet_bytes) ||
            !r.uint(c, "packet_delay_us", p, 0, 0xFFFF, d.dca1000.packet_delay_us) ||
            !r.uint(c, "fpga_timer_s", p, 0, 255, d.dca1000.fpga_timer_s)) {
            return false;
        }
        d.dca1000.present = true;
    } else if (j.contains("dca1000")) {
        return r.fail("/dca1000", "not allowed when lvds.supported is false");
    }

    out = d;
    return true;
}

CfgCommandPlan filter_cfg_commands(const std::vector<std::string>& lines, const BoardDescriptor& board) {
    CfgCommandPlan plan;
    for (std::string line : lines) {
        // trailing whitespace / CR from Windows-style cfg files
        std::string::size_type end = line.find_last_not_of(" \t\r");
        line.erase(end == std::string::npos ? 0 : end + 1);
        if (line.empty()) continue;

        bool comment = false;
        for (const std::string& pre : board.cli.skip_prefixes) {
            if (line.compare(0, pre.size(), pre) == 0) comment = true;
        }
        if (comment) continue;
        if (line.find(board.cli.start_cmd) != std::string::npos) continue;

        std::istringstream iss(line);
        std::string first;
        iss >> first;
        bool skip = false;
        for (const std::string& cmd : board.cfg_dialect.skip_commands) {
            if (first == cmd) skip = true;
        }
        (skip ? plan.skipped : plan.send).push_back(line);
    }
    return plan;
}

bool parse_json_strict(std::istream& in, const std::string& source, json& out, std::string& error) {
    // One frame per open object/array. Arrays count their elements so the
    // path names the element index; objects remember the keys seen so far.
    struct Frame {
        bool array = false;
        long index = -1;
        std::string key;
        std::set<std::string> keys;
    };
    std::vector<Frame> frames;
    std::string duplicate;  // first duplicate found, as a JSON path

    auto path = [&frames]() {
        std::string p;
        for (const Frame& f : frames) p += "/" + (f.array ? std::to_string(f.index) : f.key);
        return p;
    };
    auto element = [&frames]() {
        if (!frames.empty() && frames.back().array) frames.back().index++;
    };

    json::parser_callback_t cb = [&](int /*depth*/, json::parse_event_t ev, json& parsed) {
        switch (ev) {
            case json::parse_event_t::object_start:
            case json::parse_event_t::array_start:
                element();
                frames.push_back(Frame{});
                frames.back().array = ev == json::parse_event_t::array_start;
                break;
            case json::parse_event_t::object_end:
            case json::parse_event_t::array_end:
                if (!frames.empty()) frames.pop_back();
                break;
            case json::parse_event_t::key:
                if (!frames.empty()) {
                    Frame& f = frames.back();
                    f.key = parsed.get<std::string>();
                    if (!f.keys.insert(f.key).second && duplicate.empty()) duplicate = path();
                }
                break;
            case json::parse_event_t::value:
                element();
                break;
        }
        return true;
    };

    json j = json::parse(in, cb, /*allow_exceptions=*/false);
    if (j.is_discarded()) {
        error = source + ": not valid JSON";
        return false;
    }
    if (!duplicate.empty()) {
        std::string::size_type slash = duplicate.find_last_of('/');
        error = source + ": " + duplicate + ": duplicate key \"" + duplicate.substr(slash + 1) +
                "\" (each key may appear once per object)";
        return false;
    }
    out = std::move(j);
    return true;
}

bool BoardDescriptor::load(const std::string& path, BoardDescriptor& out, std::string& error,
                           const json* overrides) {
    std::ifstream f(path);
    if (!f.is_open()) {
        error = path + ": cannot open board descriptor";
        return false;
    }
    json j;
    if (!parse_json_strict(f, path, j, error)) return false;
    if (overrides != nullptr) {
        if (!overrides->is_object()) {
            error = path + ": board_overrides must be an object";
            return false;
        }
        j.merge_patch(*overrides);
    }
    const std::string source = overrides != nullptr ? path + " (with board_overrides)" : path;
    return from_json(j, file_stem(path), source, out, error);
}

bool BoardDescriptor::load_by_name(const std::string& boards_dir, const std::string& name,
                                   BoardDescriptor& out, std::string& error, const json* overrides) {
    if (name.empty() || name.find('/') != std::string::npos || name.find('.') != std::string::npos) {
        error = "board name \"" + name + "\" must be a plain name such as IWR1843 (no path or extension)";
        return false;
    }
    return load(boards_dir + "/" + name + ".json", out, error, overrides);
}

// ---------------------------------------------------------------------------
// Radar .cfg cross-checks
// ---------------------------------------------------------------------------
namespace {

struct CfgLine {
    int line_no;
    std::vector<std::string> tok;
};

bool parse_long(const std::string& s, long& out) {
    if (s.empty()) return false;
    errno = 0;
    char* end = nullptr;
    long v = std::strtol(s.c_str(), &end, 10);
    if (errno != 0 || end == nullptr || *end != '\0') return false;
    out = v;
    return true;
}

}  // namespace

CfgCheckResult cross_check_radar_cfg(const BoardDescriptor& b, const std::string& cfg_path,
                                     const StreamSelection& streams) {
    CfgCheckResult res;
    auto err = [&](const std::string& m) { res.errors.push_back(cfg_path + ": " + m); };
    auto note = [&](const std::string& m) { res.notes.push_back(cfg_path + ": " + m); };

    if (streams.dca1000 && !b.lvds.supported) {
        err("board " + b.name + " has lvds.supported false: DCA1000 raw-ADC streaming is not supported");
    }

    if (streams.serial && !b.data_uart.supported) {
        err("board " + b.name + " has data_uart.supported false: serial_stream.enabled is not allowed (no TLV data port)");
    }

    std::ifstream f(cfg_path);
    if (!f.is_open()) {
        err("cannot open radar cfg");
        return res;
    }

    std::vector<CfgLine> adc_cfg, adcbuf_cfg, lvds_cfg;
    std::set<std::string> seen_cmds;
    std::string text;
    int line_no = 0;
    while (std::getline(f, text)) {
        line_no++;
        std::istringstream iss(text);
        CfgLine l{line_no, {}};
        std::string t;
        while (iss >> t) l.tok.push_back(t);
        if (l.tok.empty()) continue;
        bool comment = false;
        for (const std::string& pre : b.cli.skip_prefixes) {
            if (l.tok[0].compare(0, pre.size(), pre) == 0) comment = true;
        }
        if (comment) continue;
        seen_cmds.insert(l.tok[0]);
        if (std::find(b.cfg_dialect.forbidden_commands.begin(), b.cfg_dialect.forbidden_commands.end(), l.tok[0]) !=
            b.cfg_dialect.forbidden_commands.end()) {
            err("line " + std::to_string(l.line_no) + ": command " + l.tok[0] + " is forbidden for board " + b.name +
                " (its firmware does not implement it)");
        }
        if (l.tok[0] == "adcCfg") adc_cfg.push_back(l);
        else if (l.tok[0] == "adcbufCfg") adcbuf_cfg.push_back(l);
        else if (l.tok[0] == "lvdsStreamCfg") lvds_cfg.push_back(l);
    }

    for (const std::string& cmd : b.cfg_dialect.required_commands) {
        if (!seen_cmds.count(cmd)) {
            err("required command " + cmd + " is missing (board " + b.name + " needs it)");
        }
    }

    if (!streams.dca1000 || !b.lvds.supported) return res;

    auto field = [&](const CfgLine& l, size_t idx, const char* what, long& v) -> bool {
        const std::string where = "line " + std::to_string(l.line_no) + " " + l.tok[0];
        if (l.tok.size() <= idx) {
            err(where + ": too few fields for " + what);
            return false;
        }
        if (!parse_long(l.tok[idx], v)) {
            err(where + ": " + what + " \"" + l.tok[idx] + "\" is not an integer");
            return false;
        }
        return true;
    };

    // adcCfg <numADCBits 0:12 1:14 2:16> <adcOutputFmt 0:real 1:complex1x 2:complex2x>
    if (adc_cfg.empty()) {
        err("no adcCfg line: cannot confirm 16-bit complex ADC output for DCA1000 capture");
    }
    for (const CfgLine& l : adc_cfg) {
        long bits = 0, fmt = 0;
        const std::string where = "line " + std::to_string(l.line_no) + " adcCfg";
        if (field(l, 1, "numADCBits", bits) && bits != 2) {
            err(where + ": numADCBits " + std::to_string(bits) +
                " is not 16-bit (2); the DCA1000 is configured for 16-bit data");
        }
        if (field(l, 2, "adcOutputFmt", fmt) && fmt != 1 && fmt != 2) {
            err(where + ": adcOutputFmt " + std::to_string(fmt) +
                " is real-only; the driver assumes complex samples (real output needs a *_real layout "
                "that does not exist yet)");
        }
    }

    // adcbufCfg [<subFrameIdx>] <adcOutputFmt 0:complex 1:real> <sampleSwap>
    //           <chanInterleave 0:interleaved 1:non-interleaved> <chirpThreshold>
    // SDK 3 and MCU+ have the leading subFrameIdx; the SDK 2 xWR14xx demo does not.
    const size_t off = b.sdk == Sdk::mmwave_sdk_2 ? 0 : 1;
    if (adcbuf_cfg.empty()) {
        note("no adcbufCfg line: chanInterleave and output format not cross-checked against lvds.layout");
    }
    for (const CfgLine& l : adcbuf_cfg) {
        const std::string where = "line " + std::to_string(l.line_no) + " adcbufCfg";
        if (l.tok.size() != 5 + off) {
            err(where + ": expected " + std::to_string(4 + off) + " fields for sdk " + to_string(b.sdk) + ", got " +
                std::to_string(l.tok.size() - 1));
            continue;
        }
        long fmt = 0, interleave = 0;
        if (field(l, 1 + off, "adcOutputFmt", fmt) && fmt != 0) {
            err(where + ": adcOutputFmt " + std::to_string(fmt) + " is real-only; complex (0) is required");
        }
        if (field(l, 3 + off, "chanInterleave", interleave)) {
            if (interleave != 0 && interleave != 1) {
                err(where + ": chanInterleave " + std::to_string(interleave) + " is not 0 or 1");
            } else {
                const LvdsLayout want = interleave == 0 ? LvdsLayout::lane_per_rx : LvdsLayout::two_lane_iq_pairs;
                if (want != b.lvds.layout) {
                    err(where + ": chanInterleave " + std::to_string(interleave) + " (" +
                        (interleave == 0 ? "interleaved" : "non-interleaved") + ") needs lvds.layout " +
                        to_string(want) + ", but board " + b.name + " has " + to_string(b.lvds.layout));
                }
            }
        }
    }

    // lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt 0:off 1:ADC ...> <enableSW>
    if (lvds_cfg.empty()) {
        note("no lvdsStreamCfg line: LVDS ADC streaming not confirmed by the cfg");
    }
    for (const CfgLine& l : lvds_cfg) {
        const std::string where = "line " + std::to_string(l.line_no) + " lvdsStreamCfg";
        long fmt = 0;
        if (field(l, 3, "dataFmt", fmt) && fmt != 1) {
            err(where + ": dataFmt " + std::to_string(fmt) +
                (fmt == 0 ? " disables LVDS streaming" : " is not ADC-only (1)") +
                "; DCA1000 capture needs ADC data on LVDS");
        }
    }
    return res;
}

}  // namespace radar
}  // namespace cpsl
