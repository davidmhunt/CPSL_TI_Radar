#include "CfgLimits.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>

namespace cpsl {
namespace radar {

using nlohmann::json;
using nlohmann::ordered_json;

// ---------------------------------------------------------------------------
// HostLimits
// ---------------------------------------------------------------------------
bool HostLimits::from_json(const json& j, const std::string& source, HostLimits& out, std::string& error) {
    if (!j.is_object() || !j.contains("schema") || !j.at("schema").is_number_integer() ||
        j.at("schema").get<int64_t>() != 2 || !j.contains("limits") || !j.at("limits").is_object()) {
        error = source + ": bad schema (expected {\"schema\": 2, \"limits\": {...}})";
        return false;
    }
    HostLimits h;
    for (auto it = j.at("limits").begin(); it != j.at("limits").end(); ++it) {
        const std::string p = source + ": /limits/" + it.key();
        const json& e = it.value();
        if (!e.is_object() || !e.contains("value") || !e.contains("level") || !e.contains("source") ||
            !e.contains("confidence") || !e.at("level").is_string() || !e.at("source").is_string() ||
            !e.at("confidence").is_string()) {
            error = p + ": needs value/level/source/confidence";
            return false;
        }
        FirmwareDescriptor::Limit l;
        l.value = e.at("value");
        l.level = e.at("level").get<std::string>();
        l.source = e.at("source").get<std::string>();
        l.confidence = e.at("confidence").get<std::string>();
        if ((l.level != "error" && l.level != "warning") || !l.value.is_number()) {
            error = p + ": level must be error|warning and value a number";
            return false;
        }
        h.limits[it.key()] = l;
    }
    out = h;
    return true;
}

bool HostLimits::load(const std::string& path, HostLimits& out, std::string& error) {
    std::ifstream f(path);
    if (!f.is_open()) {
        error = path + ": cannot open host limits";
        return false;
    }
    json j;
    if (!parse_json_strict(f, path, j, error)) return false;
    return from_json(j, path, out, error);
}

std::vector<CfgIssue> CfgLimitsResult::errors() const {
    std::vector<CfgIssue> r;
    for (const CfgIssue& i : issues) if (i.level == "error") r.push_back(i);
    return r;
}
std::vector<CfgIssue> CfgLimitsResult::warnings() const {
    std::vector<CfgIssue> r;
    for (const CfgIssue& i : issues) if (i.level == "warning") r.push_back(i);
    return r;
}

// ---------------------------------------------------------------------------
// cfg parsing (mirrors radar_gui/cfg/parse.py)
// ---------------------------------------------------------------------------
namespace {

struct CfgError {
    std::string msg;
};

struct Cmd {
    std::string name;
    std::vector<std::string> args;
    int line = 0;

    std::vector<double> floats() const {
        std::vector<double> v;
        for (const std::string& a : args) {
            char* end = nullptr;
            const double d = std::strtod(a.c_str(), &end);
            if (a.empty() || end == nullptr || *end != '\0') {
                throw CfgError{"line " + std::to_string(line) + ": " + name + ": could not convert string to float: '" + a + "'"};
            }
            v.push_back(d);
        }
        return v;
    }
};

struct Cfg {
    std::vector<Cmd> cmds;

    std::vector<const Cmd*> all(const std::string& n) const {
        std::vector<const Cmd*> r;
        for (const Cmd& c : cmds) if (c.name == n) r.push_back(&c);
        return r;
    }
    const Cmd* first(const std::string& n) const {
        for (const Cmd& c : cmds) if (c.name == n) return &c;
        return nullptr;
    }
    bool has(const std::string& n) const { return first(n) != nullptr; }

    int chirp_profile_id(int chirp, bool& found) const {
        found = false;
        for (const Cmd* c : all("chirpCfg")) {
            const std::vector<double> a = c->floats();
            if (a.size() >= 8 && static_cast<int>(a[0]) <= chirp && chirp <= static_cast<int>(a[1])) {
                found = true;
                return static_cast<int>(a[2]);
            }
        }
        return 0;
    }
    bool bpm_enabled() const {
        for (const Cmd* c : all("bpmCfg")) {
            const std::vector<double> a = c->floats();
            if (a.size() >= 2 && static_cast<int>(a[1]) != 0) return true;
        }
        return false;
    }
};

bool parse_cfg_file(const std::string& path, Cfg& out) {
    std::ifstream f(path);
    if (!f.is_open()) return false;
    std::string raw;
    int n = 0;
    while (std::getline(f, raw)) {
        n++;
        const std::string::size_type pc = raw.find('%');
        std::istringstream iss(pc == std::string::npos ? raw : raw.substr(0, pc));
        std::vector<std::string> tok;
        std::string t;
        while (iss >> t) tok.push_back(t);
        if (tok.empty() || tok[0][0] == '#') continue;
        Cmd c;
        c.name = tok[0];
        c.args.assign(tok.begin() + 1, tok.end());
        c.line = n;
        out.cmds.push_back(c);
    }
    return true;
}

struct Subframe {
    int index, chirp_start, num_chirps, num_loops;
    double period;
};

std::vector<Subframe> subframes(const Cfg& cfg) {
    std::vector<Subframe> out;
    const Cmd* adv = cfg.first("advFrameCfg");
    if (adv == nullptr) return out;
    for (const Cmd* c : cfg.all("subFrameCfg")) {
        const std::vector<double> a = c->floats();
        if (a.size() < 5) {
            throw CfgError{"line " + std::to_string(c->line) + ": subFrameCfg needs at least 5 fields, got " + std::to_string(a.size())};
        }
        out.push_back({static_cast<int>(a[0]), static_cast<int>(a[2]), static_cast<int>(a[3]), static_cast<int>(a[4]),
                       a.size() > 9 ? a[9] : 0.0});
    }
    std::stable_sort(out.begin(), out.end(), [](const Subframe& x, const Subframe& y) { return x.index < y.index; });
    const size_t n = adv->args.empty() ? out.size() : static_cast<size_t>(static_cast<int>(adv->floats()[0]));
    if (out.size() != n) {
        throw CfgError{"line " + std::to_string(adv->line) + ": advFrameCfg declares " + std::to_string(n) +
                       " subframes but the cfg has " + std::to_string(out.size()) + " subFrameCfg"};
    }
    return out;
}

int popcount(int64_t x) {
    int c = 0;
    uint32_t u = static_cast<uint32_t>(x & 0xFFFFFFFF);
    while (u) { c += u & 1; u >>= 1; }
    return c;
}

int bit_length(int64_t x) {   // Python int.bit_length for x >= 0; (-1).bit_length() == 1
    if (x < 0) x = -x;
    int n = 0;
    while (x) { n++; x >>= 1; }
    return n;
}

int64_t pow2(int64_t x) { return int64_t(1) << std::max(0, bit_length(x - 1)); }

int64_t valid_fft_size(int64_t n) {   // smallest 2^k or 3*2^k >= n
    int64_t best = int64_t(1) << std::max(0, bit_length(n - 1));
    int64_t three = 3;
    while (three < best) {
        if (three >= n) best = std::min(best, three);
        three *= 2;
    }
    return best;
}

std::string g(double v) {
    std::ostringstream o;
    o << std::setprecision(6) << v;
    return o.str();
}

// ---------------------------------------------------------------------------
// metrics (the subset of radar_gui/cfg/metrics.py the limit checks and --json need)
// ---------------------------------------------------------------------------
struct Met {
    bool ddma = false;
    double start_ghz = 0, slope = 0, idle_us = 0, adc_start_us = 0, ramp_us = 0, sample_rate_ksps = 0;
    int64_t num_samples = 0;
    double sweep_mhz = 0, chirp_us = 0, sampling_us = 0;
    int n_rx = 0, n_tx = 0, n_virtual = 0;
    int64_t chirps_per_loop = 0, n_loops = 0, n_chirps = 0;
    double frame_period_ms = 0, active_ms = 0, duty = 0;
    int bytes_per_sample = 4;
    int64_t bytes_per_chirp = 0, bytes_per_frame = 0;
    double avg_rate_mbps = 0;
    bool has_lvds_fmt = false;
    int lvds_fmt = 0;
};

struct FrameSpec {
    int start, end, loops;
    double period_ms;
    bool has_pid;
    int pid;
};

// (n_TX time slots per loop, azimuth TX count) of a TDM chirp pattern
std::pair<int, int> tdm_slots(const std::vector<int>& masks, bool bpm, int elev_bit) {
    int used = 0;
    for (int m : masks) used |= m;
    if (bpm) return {2, 2};
    bool all_multi = true, any_multi = false;
    for (int m : masks) {
        if (popcount(m) > 1) any_multi = true;
        else all_multi = false;
    }
    if (all_multi) return {1, 1};
    (void)any_multi;
    const int az = popcount(used & (0b111 & ~elev_bit));
    const int elev = (used & elev_bit) ? 1 : 0;
    int n_tx = az + elev;
    if (n_tx == 0) n_tx = std::max(1, popcount(used));
    return {n_tx, std::max(1, az)};
}

Met one_frame(const Cfg& cfg, bool cascade, bool ddma, int elev_bit, const FrameSpec& fr) {
    Met m;
    m.ddma = ddma;
    const Cmd* p = nullptr;
    if (!fr.has_pid) {
        p = cfg.first("profileCfg");
        if (p == nullptr) throw CfgError{"missing profileCfg"};
    } else {
        for (const Cmd* c : cfg.all("profileCfg")) {
            const std::vector<double> a = c->floats();
            if (!a.empty() && static_cast<int>(a[0]) == fr.pid) { p = c; break; }
        }
        if (p == nullptr) {
            throw CfgError{"chirps use profileId " + std::to_string(fr.pid) + " but the cfg has no such profileCfg"};
        }
    }
    const std::vector<double> pa = p->floats();
    if (pa.size() < 12) {
        throw CfgError{"line " + std::to_string(p->line) + ": profileCfg needs 14 fields, got " + std::to_string(pa.size())};
    }
    m.start_ghz = pa[1]; m.idle_us = pa[2]; m.adc_start_us = pa[3]; m.ramp_us = pa[4]; m.slope = pa[7];
    m.num_samples = static_cast<int64_t>(pa[9]);
    m.sample_rate_ksps = pa[10];
    if (m.sample_rate_ksps <= 0 || m.slope <= 0 || m.num_samples <= 0) {
        throw CfgError{"profileCfg: slope, numAdcSamples and sample rate must be positive"};
    }
    m.sampling_us = static_cast<double>(m.num_samples) * 1000.0 / m.sample_rate_ksps;
    m.sweep_mhz = m.slope * m.ramp_us;
    m.chirp_us = m.idle_us + m.ramp_us;

    const Cmd* adc = cfg.first("adcCfg");
    int adc_fmt = 1;
    if (adc != nullptr && adc->args.size() >= 2) adc_fmt = static_cast<int>(adc->floats()[1]);
    m.bytes_per_sample = adc_fmt == 0 ? 2 : 4;

    const Cmd* chc = cfg.first("channelCfg");
    if (chc == nullptr) throw CfgError{"missing channelCfg"};
    const std::vector<double> ch = chc->floats();
    if (cascade) {
        if (ch.size() < 5) throw CfgError{"cascade channelCfg needs 5 fields"};
        m.n_rx = popcount(static_cast<int64_t>(ch[0])) + popcount(static_cast<int64_t>(ch[3]));
    } else {
        m.n_rx = popcount(static_cast<int64_t>(ch.at(0)));
    }
    if (m.n_rx == 0) throw CfgError{"channelCfg enables no RX channel"};

    m.chirps_per_loop = fr.end - fr.start + 1;
    if (m.chirps_per_loop < 1 || fr.loops < 1) throw CfgError{"frameCfg: need at least one chirp and one loop"};
    // chirp -> TX mask for the frame's chirps (every chirpCfg is validated, as the Python does)
    std::map<int, int> masks;
    for (const Cmd* c : cfg.all("chirpCfg")) {
        const std::vector<double> a = c->floats();
        if (a.size() < 8) {
            throw CfgError{"line " + std::to_string(c->line) + ": chirpCfg needs 8 fields, got " + std::to_string(a.size())};
        }
        const int lo = std::max(static_cast<int>(a[0]), fr.start), hi = std::min(static_cast<int>(a[1]), fr.end);
        for (int i = lo; i <= hi; i++) masks[i] |= static_cast<int>(a[7]);
    }
    std::string missing;
    for (int i = fr.start; i <= fr.end; i++) {
        if (!masks.count(i)) missing += (missing.empty() ? "" : ", ") + std::to_string(i);
    }
    if (!missing.empty()) throw CfgError{"frameCfg uses chirp(s) [" + missing + "] with no chirpCfg"};
    std::vector<int> seq;
    for (int i = fr.start; i <= fr.end; i++) seq.push_back(masks[i]);

    if (ddma) {
        m.n_tx = popcount(static_cast<int64_t>(ch.at(1))) + (cascade ? popcount(static_cast<int64_t>(ch.at(4))) : 0);
    } else {
        m.n_tx = tdm_slots(seq, cfg.bpm_enabled(), elev_bit).first;
    }
    m.n_virtual = m.n_tx * m.n_rx;
    m.n_loops = fr.loops;
    m.n_chirps = m.chirps_per_loop * fr.loops;
    m.frame_period_ms = fr.period_ms;
    m.active_ms = static_cast<double>(m.n_chirps) * m.chirp_us * 1e-3;
    m.duty = fr.period_ms > 0 ? m.active_ms / fr.period_ms : std::numeric_limits<double>::infinity();

    const Cmd* lv = cfg.first("lvdsStreamCfg");
    if (lv != nullptr && lv->args.size() >= 3) {
        m.has_lvds_fmt = true;
        m.lvds_fmt = static_cast<int>(lv->floats()[2]);
    }
    const int meta = (m.has_lvds_fmt && m.lvds_fmt == 2) ? 64 : 0;
    m.bytes_per_chirp = m.num_samples * m.n_rx * m.bytes_per_sample + meta;
    m.bytes_per_frame = m.bytes_per_chirp * m.n_chirps;
    m.avg_rate_mbps = fr.period_ms > 0 ? static_cast<double>(m.bytes_per_frame) * 8 / (fr.period_ms * 1e3) : 0.0;
    return m;
}

}  // namespace

// ---------------------------------------------------------------------------
// the checks (mirrors radar_gui/cfg/validate.py validate())
// ---------------------------------------------------------------------------
CfgLimitsResult check_cfg_limits(const std::string& cfg_path, const std::string& gui_board,
                                 const FirmwareDescriptor& fw, const BoardDescriptor& board, const HostLimits* host) {
    using Limit = FirmwareDescriptor::Limit;
    CfgLimitsResult res;
    auto lit = fw.limits.find(gui_board);
    if (lit == fw.limits.end()) return res;
    const FirmwareDescriptor::BoardLimits& L = lit->second;

    Cfg cfg;
    if (!parse_cfg_file(cfg_path, cfg)) return res;   // cross_check_radar_cfg reports an unreadable cfg

    auto has = [&](const char* k) { return L.count(k) != 0; };
    auto num = [&](const char* k) { return L.at(k).value.get<double>(); };

    auto add = [&](const Limit& lm, const std::string& code, std::string msg, const char* level = nullptr) {
        std::string lv = level != nullptr ? level : lm.level;
        const bool weak = lm.confidence == "unverified" || lm.confidence == "low";
        if (weak && lv == "error") lv = "warning";
        if (weak) msg += " [" + lm.confidence + " limit]";
        res.issues.push_back({lv, code, msg, lm.source, lm.confidence});
    };
    auto add_key = [&](const char* key, const std::string& code, const std::string& msg, const char* level = nullptr) {
        add(L.at(key), code, msg, level);
    };
    auto add_plain = [&](const std::string& source, const std::string& code, const std::string& msg) {
        res.issues.push_back({"error", code, msg, source, ""});
    };
    auto n_errors = [&]() {
        size_t n = 0;
        for (const CfgIssue& i : res.issues) if (i.level == "error") n++;
        return n;
    };

    const bool cascade = gui_board == "AWR2243_CASCADE";
    try {
        static const char* kRequired[] = {"profileCfg", "chirpCfg", "channelCfg"};
        for (const char* name : kRequired) {
            if (!cfg.has(name)) add_plain("structure", std::string("missing_") + name, std::string("cfg has no ") + name);
        }
        const bool advanced = cfg.has("advFrameCfg");
        if (!cfg.has("frameCfg") && !(advanced && cfg.has("subFrameCfg"))) {
            add_plain("structure", "missing_frameCfg", "cfg has no frameCfg (nor advFrameCfg with subFrameCfg)");
        }
        if (n_errors() > 0) return res;

        // argument counts per dialect
        const Cmd* fc = cfg.first("frameCfg");
        const Cmd* cc = cfg.first("channelCfg");
        if (fc != nullptr && has("frame_cfg_args") && static_cast<double>(fc->args.size()) != num("frame_cfg_args")) {
            add_key("frame_cfg_args", "frame_cfg_layout",
                    "frameCfg has " + std::to_string(fc->args.size()) + " fields; " + gui_board + " expects " + g(num("frame_cfg_args")));
        }
        if (has("channel_cfg_args") && static_cast<double>(cc->args.size()) != num("channel_cfg_args")) {
            add_key("channel_cfg_args", "channel_cfg_layout",
                    "channelCfg has " + std::to_string(cc->args.size()) + " fields; " + gui_board + " expects " + g(num("channel_cfg_args")));
        }
        if (!res.issues.empty()) return res;   // metrics would misread the fields

        // metrics (the plain frame, or subframe 0 + summed totals for advFrameCfg)
        const bool ddma = fw.mimo_scheme.empty() ? cascade : fw.mimo_scheme == "ddma";
        const int elev_bit = static_cast<int>(board.elevation_tx_bit);
        Met m;
        {
            const std::vector<Subframe> subs = subframes(cfg);
            if (subs.empty()) {
                const std::vector<double> a = fc->floats();
                const size_t need = cascade ? 9 : 7;
                if (a.size() < need) {
                    throw CfgError{"line " + std::to_string(fc->line) + ": frameCfg needs " + std::to_string(need) +
                                   " fields, got " + std::to_string(a.size())};
                }
                FrameSpec fr{static_cast<int>(a[0]), static_cast<int>(a[1]), static_cast<int>(a[2]),
                             cascade ? a[5] : a[4], false, 0};
                m = one_frame(cfg, cascade, ddma, elev_bit, fr);
            } else {
                std::vector<Met> mets;
                double total = 0;
                for (const Subframe& sf : subs) {
                    bool found = false;
                    const int pid = cfg.chirp_profile_id(sf.chirp_start, found);
                    FrameSpec fr{sf.chirp_start, sf.chirp_start + sf.num_chirps - 1, sf.num_loops, sf.period, found, pid};
                    mets.push_back(one_frame(cfg, cascade, ddma, elev_bit, fr));
                    total += sf.period;
                }
                m = mets[0];
                m.frame_period_ms = total;
                m.active_ms = 0;
                m.bytes_per_frame = 0;
                for (const Met& x : mets) { m.active_ms += x.active_ms; m.bytes_per_frame += x.bytes_per_frame; }
                m.duty = total > 0 ? m.active_ms / total : std::numeric_limits<double>::infinity();
                m.avg_rate_mbps = total > 0 ? static_cast<double>(m.bytes_per_frame) * 8 / (total * 1e3) : 0.0;
            }
        }
        res.has_metrics = true;
        res.metrics = ordered_json{
            {"mode", ddma ? "ddma" : "tdm"}, {"n_rx", m.n_rx}, {"n_tx", m.n_tx}, {"n_virtual", m.n_virtual},
            {"num_samples", m.num_samples}, {"sample_rate_ksps", m.sample_rate_ksps}, {"slope_mhz_us", m.slope},
            {"start_ghz", m.start_ghz}, {"chirp_us", m.chirp_us}, {"chirps_per_loop", m.chirps_per_loop},
            {"n_loops", m.n_loops}, {"n_chirps", m.n_chirps}, {"frame_period_ms", m.frame_period_ms},
            {"active_ms", m.active_ms}, {"duty_cycle", m.duty}, {"bytes_per_chirp", m.bytes_per_chirp},
            {"bytes_per_frame", m.bytes_per_frame}, {"avg_data_rate_mbps", m.avg_rate_mbps}};

        // --- array sizes
        if (has("n_rx") && m.n_rx > num("n_rx")) {
            add_key("n_rx", "too_many_rx", std::to_string(m.n_rx) + " RX enabled, " + gui_board + " has " + g(num("n_rx")));
        }
        if (has("n_tx") && m.n_tx > num("n_tx")) {
            add_key("n_tx", "too_many_tx", std::to_string(m.n_tx) + " TX used, " + gui_board + " has " + g(num("n_tx")));
        }
        if (has("valid_tx_counts")) {
            bool ok = false;
            std::string list;
            for (const json& v : L.at("valid_tx_counts").value) {
                ok = ok || v.get<double>() == m.n_tx;
                list += (list.empty() ? "" : ", ") + g(v.get<double>());
            }
            if (!ok) {
                add_key("valid_tx_counts", "tx_count_invalid",
                        std::to_string(m.n_tx) + " TX is not a valid DDMA count; the firmware accepts [" + list + "] TX");
            }
        }

        // --- RF
        if (has("band_ghz")) {
            const double lo = L.at("band_ghz").value.at(0).get<double>(), hi = L.at("band_ghz").value.at(1).get<double>();
            const double top = m.start_ghz + m.sweep_mhz / 1e3;
            const double over_mhz = std::max((lo - m.start_ghz) * 1e3, (top - hi) * 1e3);
            constexpr double kBandTol = 5.0;
            if (over_mhz > kBandTol) {
                add_key("band_ghz", "band", "chirp spans " + g(m.start_ghz) + "-" + g(top) + " GHz, outside the " + g(lo) + "-" + g(hi) + " GHz band");
            } else {
                if (over_mhz > 1e-6) {
                    add_key("band_ghz", "band_edge",
                            "chirp spans " + g(m.start_ghz) + "-" + g(top) + " GHz, " + g(over_mhz) + " MHz past the " + g(lo) + "-" +
                                g(hi) + " GHz band edge (rounding in TI's own cfgs; accepted by the firmware)", "warning");
                }
                if (has("band_subranges_ghz")) {
                    const double tol = kBandTol / 1e3;
                    bool inside = false;
                    for (const json& r : L.at("band_subranges_ghz").value) {
                        if (r.at(0).get<double>() - tol <= m.start_ghz && top <= r.at(1).get<double>() + tol) inside = true;
                    }
                    if (!inside) {
                        add_key("band_subranges_ghz", "band_subrange",
                                "chirp spans " + g(m.start_ghz) + "-" + g(top) + " GHz; a sweep must lie wholly inside one of " +
                                    L.at("band_subranges_ghz").value.dump() + " GHz");
                    }
                }
            }
        }
        if (has("max_slope_mhz_us") && m.slope > num("max_slope_mhz_us")) {
            add_key("max_slope_mhz_us", "slope", "slope " + g(m.slope) + " MHz/us exceeds the " + gui_board + " limit of " + g(num("max_slope_mhz_us")));
        } else if (has("tested_max_slope_mhz_us") && m.slope > num("tested_max_slope_mhz_us")) {
            add_key("tested_max_slope_mhz_us", "slope_untested",
                    "slope " + g(m.slope) + " MHz/us is above the " + g(num("tested_max_slope_mhz_us")) + " this repo has tested");
        }
        // sample rate: datasheet caps are for complex 1x; real / complex 2x output allows twice that
        const Cmd* adcc = cfg.first("adcCfg");
        const int adc_fmt = (adcc != nullptr && adcc->args.size() > 1) ? static_cast<int>(adcc->floats()[1]) : 1;
        const double adc_factor = (adc_fmt == 0 || adc_fmt == 2) ? 2 : 1;
        if (has("max_sample_rate_ksps")) {
            const double cap = num("max_sample_rate_ksps") * adc_factor;
            if (m.sample_rate_ksps > cap) {
                add_key("max_sample_rate_ksps", "sample_rate", "sample rate " + g(m.sample_rate_ksps) + " ksps exceeds the " + gui_board + " maximum of " + g(cap));
            }
        }
        const Cmd* lp = cfg.first("lowPower");
        const bool low_power = lp != nullptr && lp->args.size() > 1 && static_cast<int>(lp->floats()[1]) == 1;
        if (low_power && has("lowpower_max_ksps") && m.sample_rate_ksps > num("lowpower_max_ksps") * adc_factor) {
            add_key("lowpower_max_ksps", "sample_rate_lowpower",
                    "sample rate " + g(m.sample_rate_ksps) + " ksps exceeds " + g(num("lowpower_max_ksps") * adc_factor) +
                        " ksps, the " + gui_board + " limit in low-power ADC mode (lowPower 0 1); use lowPower 0 0 or a lower rate");
        }
        if (has("min_sample_rate_ksps") && m.sample_rate_ksps < num("min_sample_rate_ksps")) {
            add_key("min_sample_rate_ksps", "sample_rate_low",
                    "sample rate " + g(m.sample_rate_ksps) + " ksps is below " + g(num("min_sample_rate_ksps")));
        }
        if (has("tested_sample_rates_ksps")) {
            bool tested = false;
            for (const json& v : L.at("tested_sample_rates_ksps").value) tested = tested || v.get<double>() == m.sample_rate_ksps;
            if (!tested) {
                add_key("tested_sample_rates_ksps", "sample_rate_untested",
                        "sample rate " + g(m.sample_rate_ksps) + " ksps is not one of TI's tested " +
                            L.at("tested_sample_rates_ksps").value.dump());
            }
        }
        if (has("min_chirp_cycle_us") && m.chirp_us < num("min_chirp_cycle_us")) {
            add_key("min_chirp_cycle_us", "chirp_cycle",
                    "chirp cycle (idle " + g(m.idle_us) + " + ramp " + g(m.ramp_us) + " us) = " + g(m.chirp_us) + " us is below the " +
                        g(num("min_chirp_cycle_us")) + " us minimum");
        }
        if (has("min_idle_us") && m.idle_us < num("min_idle_us")) {
            add_key("min_idle_us", "idle", "idle time " + g(m.idle_us) + " us is below " + g(num("min_idle_us")));
        }
        if (m.adc_start_us + m.sampling_us > m.ramp_us) {
            add_plain("physics: ADC window must end inside the ramp", "sampling_outside_ramp",
                      "ADC start " + g(m.adc_start_us) + " + sampling " + g(m.sampling_us) + " us = " +
                          g(m.adc_start_us + m.sampling_us) + " us exceeds ramp end " + g(m.ramp_us) + " us");
        }

        // --- frame
        if (has("max_loops") && static_cast<double>(m.n_loops) > num("max_loops")) {
            add_key("max_loops", "loops", "numLoops " + std::to_string(m.n_loops) + " exceeds " + g(num("max_loops")));
        }
        if (m.frame_period_ms <= 0) {
            add_plain("physics", "frame_period", "frame period must be positive");
        } else if (m.active_ms > m.frame_period_ms) {
            add_plain("physics: chirps cannot take longer than the frame", "frame_too_short",
                      "chirps take " + g(m.active_ms) + " ms but the frame period is " + g(m.frame_period_ms) + " ms");
        } else {
            if (has("min_frame_period_us") && m.frame_period_ms * 1e3 < num("min_frame_period_us")) {
                add_key("min_frame_period_us", "frame_period_short",
                        "frame period " + g(m.frame_period_ms) + " ms is below " + g(num("min_frame_period_us") / 1e3) + " ms");
            }
            if (has("max_frame_period_ms") && m.frame_period_ms > num("max_frame_period_ms")) {
                add_key("max_frame_period_ms", "frame_period_long",
                        "frame period " + g(m.frame_period_ms) + " ms exceeds " + g(num("max_frame_period_ms")) + " ms");
            }
            const double blank_us = (m.frame_period_ms - m.active_ms) * 1e3;
            if (has("min_frame_blank_us") && blank_us < num("min_frame_blank_us")) {
                add_key("min_frame_blank_us", "frame_blank",
                        "only " + g(std::round(blank_us)) + " us between the last chirp and the next frame; the radar needs about " +
                            g(num("min_frame_blank_us")) + " us");
            }
            if (host != nullptr) {
                auto duty = host->limits.find("duty_warn");
                if (duty != host->limits.end() && m.duty > duty->second.value.get<double>()) {
                    add(duty->second, "duty", "duty cycle " + g(std::round(m.duty * 100)) + "%: little time left to process each frame");
                }
            }
        }
        if (has("max_samples_silicon") && static_cast<double>(m.num_samples) > num("max_samples_silicon")) {
            add_key("max_samples_silicon", "samples_silicon",
                    std::to_string(m.num_samples) + " samples exceeds the ADC buffer limit of " + g(num("max_samples_silicon")));
        }
        if (has("max_samples") && static_cast<double>(m.num_samples) > num("max_samples")) {
            add_key("max_samples", "samples", std::to_string(m.num_samples) + " samples exceeds tested " + g(num("max_samples")));
        }
        if (has("max_chirps") && static_cast<double>(m.n_chirps) > num("max_chirps")) {
            // cascade DDM firmware: chirps per frame set the Doppler FFT size and the DSS L2 heap must hold the scratch
            const int64_t cap = static_cast<int64_t>(num("max_chirps"));
            const int64_t n_fft = valid_fft_size(m.n_chirps);
            const int64_t l2 = n_fft * (2 * m.n_virtual + 16 * m.n_rx + 8);
            const int64_t pool = has("l2_heap_bytes") ? static_cast<int64_t>(num("l2_heap_bytes")) : 0;
            const std::string fix = "reduce loops to <= " + std::to_string(cap / std::max<int64_t>(1, m.chirps_per_loop)) + " with " +
                                    std::to_string(m.chirps_per_loop) + " chirp cfgs";
            if (m.n_virtual >= 48 && m.n_rx >= 8) {
                add_key("max_chirps", "chirps",
                        std::to_string(m.n_chirps) + " chirps per frame (" + std::to_string(m.chirps_per_loop) + " per loop x " +
                            std::to_string(m.n_loops) + " loops) exceeds the " + std::to_string(cap) + "-chirp limit of the cascade firmware (Doppler FFT size " +
                            std::to_string(n_fft) + " needs ~" + std::to_string(l2 / 1024) + " KiB of the 82 KiB DSS L2 heap); " + fix);
            } else {
                add_key("max_chirps", "chirps",
                        std::to_string(m.n_chirps) + " chirps exceeds " + std::to_string(cap) + ", which is only bench-tested with 6 TX / 8 RX; with " +
                            std::to_string(m.n_tx) + " TX / " + std::to_string(m.n_rx) + " RX the L2 model estimates ~" + std::to_string(l2 / 1024) +
                            " KiB of " + std::to_string(pool / 1024) + " KiB for this Doppler size (untested); " + fix, "warning");
            }
        }
        if (has("l3_cube_bytes") && ddma) {
            double rho = 1.0;
            const Cmd* comp = cfg.first("compressionCfg");
            if (comp != nullptr && comp->args.size() > 3 && static_cast<int>(comp->floats()[1]) == 1) rho = comp->floats()[3];
            const int64_t r = valid_fft_size(m.num_samples), c = m.n_chirps, n_fft = valid_fft_size(c);
            const int64_t need = static_cast<int64_t>(static_cast<double>(r * c * m.n_rx * 4) * rho) + c * m.n_rx * 32 +
                                 r * (n_fft / 8) * 2 + 64 * 1024;
            const int64_t cap = static_cast<int64_t>(num("l3_cube_bytes"));
            if (need > cap) {
                add_key("l3_cube_bytes", "radar_cube_l3",
                        "radar cube + scratch ~" + std::to_string(need) + " B (" + std::to_string(r) + " range bins x " + std::to_string(c) +
                            " chirps x " + std::to_string(m.n_rx) + " RX, compression " + g(rho) + ") exceeds the " + std::to_string(cap) +
                            " B L3 RAM of the cascade DSS; reduce samples (range bins) or loops, or lower the compression ratio");
            }
        }
        const bool demo = cfg.has("guiMonitor") || cfg.has("cfarCfg");
        if (has("adc_buffer_bytes")) {
            const int64_t chirp_b = m.num_samples * m.n_rx * m.bytes_per_sample;
            if (static_cast<double>(chirp_b) > num("adc_buffer_bytes")) {
                add_key("adc_buffer_bytes", "adc_buffer",
                        "one chirp is " + std::to_string(chirp_b) + " B, larger than the " + g(num("adc_buffer_bytes")) + " B ADC buffer");
            } else if (has("adc_buffer_streaming_bytes") && static_cast<double>(chirp_b) > num("adc_buffer_streaming_bytes") &&
                       ((m.has_lvds_fmt && m.lvds_fmt != 0) || !demo)) {
                add_key("adc_buffer_streaming_bytes", "adc_buffer_streaming",
                        "one chirp is " + std::to_string(chirp_b) + " B; when streaming over LVDS only a " + g(num("adc_buffer_streaming_bytes")) +
                            " B ping/pong half is usable per chirp");
            }
        }

        // --- on-chip demo memory (not applicable to raw-ADC cfgs)
        if (has("l3_radar_cube_bytes") && demo) {
            const int64_t cube = pow2(m.num_samples) * pow2(m.n_loops) * m.n_virtual * 4;
            if (static_cast<double>(cube) > num("l3_radar_cube_bytes")) {
                add_key("l3_radar_cube_bytes", "radar_cube",
                        "radar cube ~" + std::to_string(cube) + " B (range x doppler x virtual x 4) exceeds L3 " + g(num("l3_radar_cube_bytes")) + " B");
            }
        }

        // --- LVDS / DCA1000
        if (m.has_lvds_fmt && m.lvds_fmt != 0) {
            auto out = fw.outputs.find(gui_board);
            if (out != fw.outputs.end() && !out->second.lvds) {
                add_plain("config/firmware/" + fw.id + ".json", "lvds_not_in_firmware",
                          "lvdsStreamCfg is enabled but firmware '" + fw.id + "' has no LVDS output on " + gui_board);
            }
            if (has("lvds_supported") && !L.at("lvds_supported").value.get<bool>()) {
                add_key("lvds_supported", "lvds_unsupported", "lvdsStreamCfg is enabled but " + gui_board + " has no LVDS output", "warning");
            } else {
                const Cmd* lv = cfg.first("lvdsStreamCfg");
                const bool header_on = lv != nullptr && lv->args.size() > 1 && static_cast<int>(lv->floats()[1]) != 0;
                const int64_t one_chirp = m.num_samples * m.n_rx * m.bytes_per_sample;
                if (has("lvds_min_transfer_bytes") && !header_on && static_cast<double>(one_chirp) < num("lvds_min_transfer_bytes")) {
                    add_key("lvds_min_transfer_bytes", "lvds_min_transfer",
                            "one chirp is " + std::to_string(one_chirp) + " B, below the " + g(num("lvds_min_transfer_bytes")) +
                                " B CBUFF minimum transfer; enable the HSI header in lvdsStreamCfg or use more samples");
                }
                if (has("lvds_min_samples") && static_cast<double>(m.num_samples) < num("lvds_min_samples")) {
                    add_key("lvds_min_samples", "lvds_min_samples",
                            "TI supports LVDS streaming of the demo for at least " + g(num("lvds_min_samples")) +
                                " ADC samples per chirp, cfg has " + std::to_string(m.num_samples));
                }
                if (has("lvds_chirp_overhead_bytes") && has("lvds_chirp_align_bytes") && has("lvds_lanes") && has("lvds_lane_mbps")) {
                    int64_t need = m.bytes_per_chirp + static_cast<int64_t>(num("lvds_chirp_overhead_bytes"));
                    const int64_t align = static_cast<int64_t>(num("lvds_chirp_align_bytes"));
                    need = (need + align - 1) / align * align;
                    const double cap_b = m.chirp_us * num("lvds_lanes") * num("lvds_lane_mbps") / 8;
                    if (static_cast<double>(need) > cap_b) {
                        add_key("lvds_lane_mbps", "lvds_rate",
                                "each chirp sends " + std::to_string(need) + " B over LVDS (ADC data + header, rounded up) but a chirp cycle of " +
                                    g(m.chirp_us) + " us carries only " + g(std::round(cap_b)) + " B on " + g(num("lvds_lanes")) + " lanes x " +
                                    g(num("lvds_lane_mbps")) + " Mbps; the firmware will not stream this cfg");
                    }
                }
                if (host != nullptr) {
                    auto eth = host->limits.find("dca1000_ethernet_mbps");
                    auto mx = host->limits.find("dca1000_max_mbps");
                    auto ov = host->limits.find("dca1000_packet_overhead_us");
                    if (eth != host->limits.end() && m.avg_rate_mbps > eth->second.value.get<double>()) {
                        add(eth->second, "dca_rate", "average " + g(std::round(m.avg_rate_mbps)) + " Mbps exceeds the 1 Gb/s DCA1000 link");
                    } else if (mx != host->limits.end() && ov != host->limits.end() && board.dca1000.present) {
                        const double ceil_mbps = std::min(mx->second.value.get<double>(),
                                                          board.dca1000.packet_bytes * 8.0 / (board.dca1000.packet_delay_us + ov->second.value.get<double>()));
                        if (m.avg_rate_mbps > ceil_mbps) {
                            add(mx->second, "dca_rate_high",
                                "average " + g(std::round(m.avg_rate_mbps)) + " Mbps is above the ~" + g(std::round(ceil_mbps)) +
                                    " Mbps the DCA1000 sustains at the driver's " + std::to_string(board.dca1000.packet_delay_us) +
                                    " us packet delay (lower the delay to raise it)");
                        }
                    }
                }
            }
        }
    } catch (const CfgError& e) {
        add_plain("parse", "bad_cfg", e.msg);
    } catch (const std::exception& e) {
        add_plain("parse", "bad_cfg", std::string("malformed cfg: ") + e.what());
    }
    return res;
}

}  // namespace radar
}  // namespace cpsl
