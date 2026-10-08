#ifndef SYSTEM_CONFIG_READER_H
#define SYSTEM_CONFIG_READER_H

// System config, schema v2 (driver v2 design §2): one JSON file naming a board
// descriptor, a radar .cfg, the ports and what to stream and save.
//
// Loading is strict: unknown keys, wrong types and out-of-range values are
// errors naming the file and JSON path, and so is a repeated key. A file
// without "schema_version" is a v1 config and is rejected with the name of
// the migration script (tools/migrate_config_v1_to_v2.py). Loading also
// resolves the board descriptor (with board_overrides merged in) and runs
// cross_check_radar_cfg for the enabled streams; any error there fails the
// load. Nothing here throws; on failure `initialized` is false and
// get_error() holds the message (not logged: the caller reports it).
//
// Paths ("radar_cfg", a "board" path, "output.dir") are relative to the JSON
// file's directory unless absolute. A plain board name (e.g. IWR1843) is
// looked up as <boards dir>/<name>.json, where the boards dir is
// $CPSL_TI_RADAR_BOARDS_DIR if set, otherwise <JSON dir>/../boards (the
// layout of CPSL_TI_Radar_cpp/config/).
//
// "firmware" (gui-04) names the firmware descriptor
// (<boards dir>/../firmware/<id>.json, or $CPSL_TI_RADAR_FIRMWARE_DIR) the
// config is meant for. When present it must be in the board's "firmwares" list
// and agree with the descriptor's driver_board mapping (firmware
// iwr1843_sar_lvds runs with board IWR1843_SAR, not IWR1843), and the enabled
// streams must be outputs of that firmware on the board. It is optional in
// this version of the driver and becomes required in a later commit.
//
// The firmware also supplies the cfg command rules (cfg_rules: skip / required / forbidden commands) and the
// CLI prompt (cli_overrides) of the board it runs on (gui-33). Without a "firmware" key the board's default
// firmware (first of its "firmwares" list) is used; getBoard() already carries the result.

#include <cstdint>
#include <string>
#include <vector>

#include "nlohmann/json.hpp"
#include "BoardDescriptor.hpp"
#include "FirmwareDescriptor.hpp"
#include "CfgLimits.hpp"
#include "FirmwareIdentity.hpp"
#include "Log.hpp"

using json = nlohmann::json;

// runtime.log_level (cpsl::radar::LogLevel; the alias keeps older callers building)
using LogLevel = cpsl::radar::LogLevel;

class SystemConfigReader {
    public:
        static constexpr int kSchemaVersion = 2;
        static constexpr const char* kMigrationScript = "tools/migrate_config_v1_to_v2.py";
        static constexpr const char* kBoardsDirEnv = "CPSL_TI_RADAR_BOARDS_DIR";
        static constexpr const char* kFirmwareDirEnv = "CPSL_TI_RADAR_FIRMWARE_DIR";

        // One load problem, machine-readable (--validate --json). `source` is the file that defines the
        // violated rule or holds the bad value (system JSON, board or firmware descriptor, radar cfg).
        struct Issue {
            std::string code;
            std::string message;
            std::string source;
        };

        SystemConfigReader();
        explicit SystemConfigReader(const std::string& jsonFilePath);

        // (Re)load from a file; returns `initialized`.
        bool initialize(const std::string& jsonFilePath);

        const std::string& get_error() const { return error; }
        const std::string& get_json_file_path() const { return json_file_path; }

        // board descriptor, with board_overrides already applied
        const cpsl::radar::BoardDescriptor& getBoard() const { return board; }
        const std::string& getBoardPath() const { return board_path; }
        // "" when the config has no "firmware" key
        const std::string& getFirmwareId() const { return firmware_id; }
        const cpsl::radar::FirmwareDescriptor& getFirmware() const { return firmware; }
        const std::string& getFirmwarePath() const { return firmware_path; }
        // The problems of a failed load, one per error (get_error() joins them); empty after a successful load.
        const std::vector<Issue>& getIssues() const { return issues; }
        // cross_check_radar_cfg notes (a check that could not be made; not fatal)
        const std::vector<std::string>& getCfgCheckNotes() const { return cfg_notes; }
        // warning-level cfg limit findings of a successful load (gui-04 Step 3b; `source` = the violated limit's source)
        const std::vector<Issue>& getCfgWarnings() const { return cfg_warnings; }
        // cheap subset of the GUI metrics for --validate --json (empty object when the limits were not checked)
        const nlohmann::ordered_json& getCfgMetrics() const { return cfg_metrics; }

        std::string getRadarConfigPath() const { return radar_cfg_path; }
        std::string getRadarCliPort() const { return cli_port; }
        std::string getRadarDataPort() const { return serial_port; }
        unsigned int getRadarCliBaudRate() const { return board.cli.baud; }
        int getRadarCliTimeoutMs() const { return static_cast<int>(board.cli.cmd_timeout_ms); }
        unsigned int getRadarDataBaudRate() const { return board.data_uart.baud; }
        int getRadarDataTimeoutMs() const { return static_cast<int>(board.data_uart.timeout_ms); }

        bool get_serial_streaming_enabled() const { return serial_enabled; }
        bool get_dca1000_streaming_enabled() const { return dca_enabled; }
        std::string getDCAFpgaIP() const { return dca_fpga_ip; }
        std::string getDCASystemIP() const { return dca_host_ip; }
        int getDCADataPort() const { return dca_data_port; }
        int getDCACmdPort() const { return dca_cmd_port; }
        size_t getDCARcvbufBytes() const { return dca_rcvbuf_bytes; }

        // output.dir resolved against the JSON directory; "" = current directory
        std::string get_output_dir() const { return output_dir; }
        bool get_save_adc_frames() const { return save_adc_frames; }
        bool get_save_raw_lvds() const { return save_raw_lvds; }
        // serial data-port bytes as read, to serial_data.bin in output.dir
        bool get_save_serial_bytes() const { return save_serial_bytes; }
        // output_dir + "/" + name, or just name when output_dir is ""
        std::string get_output_path(const std::string& name) const;

        LogLevel get_log_level() const { return log_level; }
        // true at log_level "debug" (the v1 "verbose": per-frame status lines)
        bool get_verbose() const { return log_level == LogLevel::debug; }

        // runtime.* values: frame_queue_depth (DCA1000Handler frame queue),
        // stall_timeout_ms (Radar stall policy), rx_cpu / rx_priority (the
        // DCA1000 RX thread) and worker_cpu / worker_priority (the DCA worker
        // thread; ThreadPlacement.hpp)
        uint32_t get_frame_queue_depth() const { return frame_queue_depth; }
        uint32_t get_stall_timeout_ms() const { return stall_timeout_ms; }
        // runtime.skip_configure (or the driver's --skip-configure): open the ports but send no radar cfg,
        // no sensorStart and no sensorStop; for a board already configured and streaming this power-up
        bool get_skip_configure() const { return skip_configure; }
        void set_skip_configure(bool v) { skip_configure = v; }
        // runtime.firmware_check (gui-33): auto (default) | warn | off; see Radar::configure
        cpsl::radar::FirmwareCheck get_firmware_check() const { return firmware_check; }
        int get_rx_cpu() const { return rx_cpu; }          // -1 = null (not pinned)
        int get_worker_cpu() const { return worker_cpu; }  // -1 = null (not pinned)
        uint32_t get_rx_priority() const { return rx_priority; }
        uint32_t get_worker_priority() const { return worker_priority; }

        //variable to confirm that the class has been initialized
        bool initialized;

    private:
        void reset();
        bool load();
        bool load_issue(const std::string& code, const std::string& message, const std::string& source);
        bool check_firmware(const std::string& src, const std::string& boards_dir_hint);

        std::string json_file_path;
        std::string error;

        cpsl::radar::BoardDescriptor board;
        std::string board_path;
        std::string firmware_id;
        cpsl::radar::FirmwareDescriptor firmware;
        std::string firmware_path;
        std::vector<Issue> issues;
        std::vector<std::string> cfg_notes;
        std::vector<Issue> cfg_warnings;
        nlohmann::ordered_json cfg_metrics;
        cpsl::radar::FirmwareDescriptor default_fw;   // the board's default firmware, when the config names none

        std::string radar_cfg_path;
        std::string cli_port;

        bool serial_enabled;
        std::string serial_port;

        bool dca_enabled;
        std::string dca_fpga_ip;
        std::string dca_host_ip;
        int dca_cmd_port;
        int dca_data_port;
        size_t dca_rcvbuf_bytes;

        std::string output_dir;
        bool save_adc_frames;
        bool save_raw_lvds;
        bool save_serial_bytes;

        LogLevel log_level;
        uint32_t frame_queue_depth;
        uint32_t stall_timeout_ms;
        bool skip_configure;
        cpsl::radar::FirmwareCheck firmware_check;
        int rx_cpu;
        int worker_cpu;
        uint32_t rx_priority;
        uint32_t worker_priority;
};

#endif // SYSTEM_CONFIG_READER_H
