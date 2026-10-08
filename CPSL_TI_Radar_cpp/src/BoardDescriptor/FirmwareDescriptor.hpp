#ifndef CPSL_RADAR_FIRMWARE_DESCRIPTOR_HPP
#define CPSL_RADAR_FIRMWARE_DESCRIPTOR_HPP

// Firmware descriptor (directive gui-04): what one firmware image provides per
// board, loaded from config/firmware/<id>.json (schema 2). The same files feed
// the host GUI (radar_gui/cfg/firmware.py), so the driver and the GUI share one
// source of truth for the per-firmware limits.
//
// Loading is as strict as BoardDescriptor: duplicate keys, unknown keys, wrong
// types and inconsistent fields are load errors naming the file and JSON path.
// Nothing here throws, prints or exits.
//
// The driver reads: id, outputs, templates, driver_board, system_enables,
// limits, identify (gui-33: what the board answers when asked, see
// FirmwareIdentity.hpp), cfg_rules and cli_overrides (gui-33 Step 4: the cfg command rules
// and CLI prompt that depend on the firmware image, not the silicon). Keys that only the GUI
// uses are listed in gui_only_keys() (the one place to extend: gui-35 adds "detection") and
// are accepted but not interpreted; every other unknown key is an error.
//
// cfg_rules_for()/cli_prompt_for() are the one accessor for "firmware X on board Y"; the
// default firmware of a board without a "firmware" key is default_firmware_id() (the first
// entry of the board's "firmwares" list, the one the GUI infers).

#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

#include "BoardDescriptor.hpp"  // LvdsStreamFormat

namespace cpsl {
namespace radar {

struct FirmwareDescriptor {
    static constexpr int kSchema = 2;

    // Top-level keys the GUI owns (checked by radar_gui/cfg/firmware.py); the driver ignores them.
    static const std::set<std::string>& gui_only_keys();

    struct Output {
        bool tlv = false;   // point cloud over the data UART
        bool lvds = false;  // ADC samples over LVDS
    };
    struct Limit {
        nlohmann::json value;     // number, bool, or array (shape depends on the limit name)
        std::string level;        // "error" or "warning"
        std::string source;
        std::string confidence;
    };
    using BoardLimits = std::map<std::string, Limit>;

    // identify.<board> (gui-33): the probes that tell this firmware from the others. Regexes use the
    // subset shared by Python `re` and C++ std::regex ECMAScript (checked at load).
    struct IdentifyProbe {
        std::string cmd;
        std::vector<std::string> require;  // every one must match the reply
        std::vector<std::string> reject;   // none may match
        // field -> regex with one group, in display order (platform, sdk, device first, then the rest sorted)
        std::vector<std::pair<std::string, std::string>> show;
    };
    struct Identify {
        std::string level;        // "bench" | "source" | "unverified"
        int timeout_ms = 1000;
        bool once_safe = false;   // required true to query a config_once_per_boot board
        bool has_once_safe = false;
        std::vector<IdentifyProbe> probes;
        std::string flash_hint;
        std::string note;
    };

    // cfg_rules.<board> (gui-33 Step 4): commands the firmware rejects (left in the cfg file, never
    // sent), needs, or does not implement. Each entry is one command word.
    struct CfgRules {
        std::vector<std::string> skip_commands;
        std::vector<std::string> required_commands;
        std::vector<std::string> forbidden_commands;
    };

    int schema = 0;
    std::string id;
    std::string description;
    // keyed by the GUI board name (the keys of templates are the boards the firmware supports)
    std::map<std::string, Output> outputs;
    std::map<std::string, std::string> templates;
    // GUI board -> driver board (config/boards/<name>.json) a system JSON names for this firmware
    std::map<std::string, std::string> driver_board;
    bool enable_serial = false;   // system_enables.serial
    bool enable_dca1000 = false;  // system_enables.dca1000
    std::map<std::string, BoardLimits> limits;
    // keyed by the GUI board name; absent = no identify data for that board
    std::map<std::string, Identify> identify;
    // keyed by the GUI board name; absent = no rules for that board
    std::map<std::string, CfgRules> cfg_rules;
    // cli_overrides.<board>.prompt: the CLI prompt this firmware prints on that board (overrides the board
    // descriptor's cli.prompt, which is the prompt of the stock firmware)
    std::map<std::string, std::string> cli_prompt;
    // mimo.scheme ("tdm" | "ddma"; "" = no mimo block): the only part of the GUI-owned `mimo` block the driver reads,
    // because the TX count of the cfg limit checks depends on it. The rest of `mimo` stays GUI-only.
    std::string mimo_scheme;
    // lvds_data_fmts.formats (core-24): lvdsStreamCfg dataFmt -> what the LVDS stream carries on this image.
    // Empty = key absent = {1: adc}. apply_firmware_to_board copies it to BoardDescriptor::Lvds::stream_formats.
    std::map<int, LvdsStreamFormat> lvds_stream_formats;

    // Load and validate a descriptor file. `id` must equal the file's stem.
    static bool load(const std::string& path, FirmwareDescriptor& out, std::string& error);
    // load(firmware_dir + "/" + id + ".json", ...). `id` must be a plain id (no separators or dots).
    static bool load_by_id(const std::string& firmware_dir, const std::string& id, FirmwareDescriptor& out,
                           std::string& error);
    static bool from_json(const nlohmann::json& j, const std::string& expected_id, const std::string& source,
                          FirmwareDescriptor& out, std::string& error);

    // The accessor: rules / prompt of this firmware on the DRIVER board `driver_board_name` (config/boards/<name>.json;
    // IWR1843_SAR is looked up as the GUI board IWR1843). Empty rules / "" when the descriptor has none.
    CfgRules cfg_rules_for(const std::string& driver_board_name) const;
    std::string cli_prompt_for(const std::string& driver_board_name) const;

    bool supports_board(const std::string& gui_board) const { return templates.count(gui_board) != 0; }
    // The descriptor's name for a driver board: the GUI board whose driver_board is `driver_board_name`
    // (IWR1843_SAR -> IWR1843), or `driver_board_name` itself when no driver_board entry maps to it.
    std::string gui_board_for(const std::string& driver_board_name) const;
    // The driver board a system JSON names for `gui_board` (driver_board entry, else `gui_board`).
    std::string driver_board_for(const std::string& gui_board) const;
};

// The default firmware id of a board: the first entry of its "firmwares" list ("" = the board lists none).
// A system config without a "firmware" key is treated as this firmware for cfg rules / prompt.
std::string default_firmware_id(const BoardDescriptor& board);

// Apply `fw`'s cfg_rules and prompt for `board` to the board descriptor's cfg_dialect / cli.prompt (the fields
// every downstream user already reads). `keep_prompt` = the system config's board_overrides set cli.prompt,
// which then wins. Fails (error names the descriptor) if a skipped command is the board's start/stop command.
bool apply_firmware_to_board(const FirmwareDescriptor& fw, const std::string& fw_path, bool keep_prompt,
                             BoardDescriptor& board, std::string& error);

}  // namespace radar
}  // namespace cpsl

#endif  // CPSL_RADAR_FIRMWARE_DESCRIPTOR_HPP
