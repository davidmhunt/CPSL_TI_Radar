#ifndef CPSL_RADAR_BOARD_DESCRIPTOR_HPP
#define CPSL_RADAR_BOARD_DESCRIPTOR_HPP

// Board descriptor (driver v2 design §1): everything the driver needs to know
// about one radar board, loaded from config/boards/<name>.json.
//
// Loading is strict: unknown keys, wrong types, unknown enum strings and
// inconsistent fields are load errors with a message naming the file and the
// JSON path. Nothing here throws, prints or exits.
//
// cross_check_radar_cfg() checks a TI radar .cfg against a descriptor for the
// streams a run enables (design §1 "Cross-checks against the radar cfg").
//
// Not wired into Runner or main yet (core-10 does that).

#include <cstdint>
#include <istream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace cpsl {
namespace radar {

enum class Sdk { mmwave_sdk_2, mmwave_sdk_3, mmwave_mcuplus };
enum class TlvDialect { sdk3, sdk2, mcuplus_cascade };
enum class LvdsLayout { two_lane_iq_pairs, lane_per_rx };
enum class IqOrder { i_first, q_first };

const char* to_string(Sdk v);
const char* to_string(TlvDialect v);
const char* to_string(LvdsLayout v);
const char* to_string(IqOrder v);

struct BoardDescriptor {
    static constexpr int kSchema = 1;

    struct Cli {
        uint32_t baud = 0;
        std::string ack;
        std::vector<std::string> error_tokens;
        std::string prompt;
        uint32_t prompt_wait_ms = 0;
        uint32_t cmd_timeout_ms = 0;
        std::string start_cmd;
        std::string stop_cmd;
        std::vector<std::string> skip_prefixes;
    };
    struct Lifecycle {
        bool config_once_per_boot = false;
    };
    struct CfgDialect {
        std::vector<uint32_t> rx_mask_fields;  // channelCfg field indices (command = 0)
        uint32_t frame_period_field = 0;       // frameCfg field index of the period
    };
    struct DataUart {
        uint32_t baud = 0;
        uint32_t header_bytes = 0;
        TlvDialect tlv_dialect = TlvDialect::sdk3;
        uint32_t timeout_ms = 0;
    };
    struct Lvds {
        bool supported = false;
        // valid only when supported
        uint32_t lanes = 0;
        LvdsLayout layout = LvdsLayout::two_lane_iq_pairs;
        IqOrder iq_order = IqOrder::i_first;
    };
    struct Dca1000 {
        bool present = false;  // block is required when lvds.supported, absent otherwise
        uint32_t packet_bytes = 0;
        uint32_t packet_delay_us = 0;
        uint32_t fpga_timer_s = 0;
    };

    int schema = 0;
    std::string name;
    Sdk sdk = Sdk::mmwave_sdk_3;
    Cli cli;
    Lifecycle lifecycle;
    CfgDialect cfg_dialect;
    DataUart data_uart;
    Lvds lvds;
    Dca1000 dca1000;

    // Load and validate a descriptor file. `name` must equal the file's stem.
    // If `overrides` is given (the system config's board_overrides object) it
    // is deep-merged (JSON merge patch) before validation, so an override can
    // never introduce an unknown key or a bad value. Returns false and sets
    // `error` on any problem; `out` is only written on success.
    static bool load(const std::string& path, BoardDescriptor& out, std::string& error,
                     const nlohmann::json* overrides = nullptr);

    // load(boards_dir + "/" + name + ".json", ...). `name` must be a plain
    // board name (no path separators).
    static bool load_by_name(const std::string& boards_dir, const std::string& name,
                             BoardDescriptor& out, std::string& error,
                             const nlohmann::json* overrides = nullptr);

    // Validate an already-parsed document. `expected_name` (if non-empty) must
    // equal the "name" field. `source` prefixes error messages.
    static bool from_json(const nlohmann::json& j, const std::string& expected_name,
                          const std::string& source, BoardDescriptor& out, std::string& error);
};

// Parse JSON without exceptions, rejecting duplicate object keys (nlohmann
// would otherwise keep the last one silently). On failure returns false and
// sets `error` to "<source>: not valid JSON" or
// "<source>: <json path>: duplicate key \"<k>\"".
bool parse_json_strict(std::istream& in, const std::string& source, nlohmann::json& out, std::string& error);

// Which streams a run enables (from the system config).
struct StreamSelection {
    bool dca1000 = false;
    bool serial = false;
};

struct CfgCheckResult {
    std::vector<std::string> errors;  // the run would produce garbage or fail: refuse it
    std::vector<std::string> notes;   // a check could not be made (line absent); not fatal
    bool ok() const { return errors.empty(); }
};

// Cross-check a TI radar .cfg against the board for the enabled streams:
//   - DCA1000 requested on a board with lvds.supported == false
//   - serial requested with the unconfirmed sdk2 TLV dialect (design D7)
//   - DCA1000: adcCfg must be 16-bit and complex; adcbufCfg must be complex
//     and its chanInterleave must match lvds.layout; lvdsStreamCfg must
//     stream ADC data only (dataFmt 1)
CfgCheckResult cross_check_radar_cfg(const BoardDescriptor& board, const std::string& cfg_path,
                                     const StreamSelection& streams);

}  // namespace radar
}  // namespace cpsl

#endif  // CPSL_RADAR_BOARD_DESCRIPTOR_HPP
