#ifndef CPSL_RADAR_CFG_LIMITS_HPP
#define CPSL_RADAR_CFG_LIMITS_HPP

// Radar .cfg limit checks (directive gui-04 Step 3b): the error-level (and, reported separately, warning-level)
// rules of the GUI validator (radar_gui/cfg/validate.py + metrics.py), driven by the same data: the firmware
// descriptor's `limits.<board>` (FirmwareDescriptor) and config/limits/host.json (HostLimits). Every issue
// carries the Python rule `code`, so the driver and the GUI agree code for code.
//
// Ported: structure (missing_*), frame/channel cfg arg counts, TX/RX counts, band and sub-band, slope, sample
// rate (incl. low-power), chirp cycle, idle, loops, frame period / blank, ADC buffer, silicon/tested samples,
// the cascade chirp and L3 cube limits, the on-chip demo radar cube, LVDS rate / min transfer / min samples
// and the DCA1000 link rate. Required/forbidden commands are checked by cross_check_radar_cfg (one accessor,
// FirmwareDescriptor::cfg_rules_for). NOT ported: the MIMO / chirp-pattern rules (mimo_issues in validate.py),
// which depend on the GUI-only `mimo` block.
//
// Pure: reads the cfg file, throws nothing, prints nothing.

#include <map>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "BoardDescriptor.hpp"
#include "FirmwareDescriptor.hpp"

namespace cpsl {
namespace radar {

// config/limits/host.json: board-independent limits, same entry shape as the firmware descriptors' limits.
struct HostLimits {
    std::map<std::string, FirmwareDescriptor::Limit> limits;

    static bool load(const std::string& path, HostLimits& out, std::string& error);
    static bool from_json(const nlohmann::json& j, const std::string& source, HostLimits& out, std::string& error);
};

struct CfgIssue {
    std::string level;       // "error" | "warning"
    std::string code;        // the Python rule code
    std::string message;
    std::string source;      // where the violated limit comes from (limit source, or a physics note)
    std::string confidence;  // of the limit behind it ("" for structure / physics rules)
};

struct CfgLimitsResult {
    std::vector<CfgIssue> issues;
    bool has_metrics = false;
    nlohmann::ordered_json metrics = nlohmann::ordered_json::object();   // cheap subset of the GUI metrics

    std::vector<CfgIssue> errors() const;
    std::vector<CfgIssue> warnings() const;
};

// Check `cfg_path` against the limits of `fw` for `gui_board` (the descriptor's board key; IWR1843 for the
// driver board IWR1843_SAR). `board` is the driver board (dca1000 packet params, elevation TX bit); `host`
// may be null (the DCA1000 link checks are then skipped). If `fw` has no limits for the board the result is empty.
CfgLimitsResult check_cfg_limits(const std::string& cfg_path, const std::string& gui_board,
                                 const FirmwareDescriptor& fw, const BoardDescriptor& board, const HostLimits* host);

}  // namespace radar
}  // namespace cpsl

#endif  // CPSL_RADAR_CFG_LIMITS_HPP
