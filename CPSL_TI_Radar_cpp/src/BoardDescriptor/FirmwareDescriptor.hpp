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
// limits. Keys that only the GUI uses are listed in gui_only_keys() (the one
// place to extend: gui-35 adds "detection") and are accepted but not
// interpreted; every other unknown key is an error.

#include <map>
#include <set>
#include <string>

#include <nlohmann/json.hpp>

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

    // Load and validate a descriptor file. `id` must equal the file's stem.
    static bool load(const std::string& path, FirmwareDescriptor& out, std::string& error);
    // load(firmware_dir + "/" + id + ".json", ...). `id` must be a plain id (no separators or dots).
    static bool load_by_id(const std::string& firmware_dir, const std::string& id, FirmwareDescriptor& out,
                           std::string& error);
    static bool from_json(const nlohmann::json& j, const std::string& expected_id, const std::string& source,
                          FirmwareDescriptor& out, std::string& error);

    bool supports_board(const std::string& gui_board) const { return templates.count(gui_board) != 0; }
    // The descriptor's name for a driver board: the GUI board whose driver_board is `driver_board_name`
    // (IWR1843_SAR -> IWR1843), or `driver_board_name` itself when no driver_board entry maps to it.
    std::string gui_board_for(const std::string& driver_board_name) const;
    // The driver board a system JSON names for `gui_board` (driver_board entry, else `gui_board`).
    std::string driver_board_for(const std::string& gui_board) const;
};

}  // namespace radar
}  // namespace cpsl

#endif  // CPSL_RADAR_FIRMWARE_DESCRIPTOR_HPP
