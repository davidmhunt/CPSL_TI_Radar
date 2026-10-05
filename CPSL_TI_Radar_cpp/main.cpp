//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <csignal>
#include <exception>
#include <fstream>
#include <vector>

//JSON handling
#include "Runner.hpp"

using json = nlohmann::json;

Runner* runner_global = nullptr;


void signalHandler(int signum){
    std::cout << "Interrupt signal (" << signum << ") received.\n";
    if (runner_global && runner_global->initialized) {
        runner_global->stop();
    }

    exit(0);
}

static void print_usage(const char* prog){
    std::cerr << "usage: " << prog << " <system.json> [--validate]\n"
              << "  <system.json>  system config, schema v2 (v1 files: uv run "
              << SystemConfigReader::kMigrationScript << ")\n"
              << "  --validate     load and cross-check the config (board descriptor, radar cfg)\n"
              << "                 without opening any port or socket; exit 0 if it is usable"
              << std::endl;
}

static std::string join(const std::vector<uint32_t>& v){
    std::string s;
    for (uint32_t x : v) s += (s.empty() ? "" : ",") + std::to_string(x);
    return s;
}

/**
 * @brief --validate: everything a run would check before touching hardware.
 * Loads the system config (which resolves the board descriptor with its
 * board_overrides and runs cross_check_radar_cfg), parses the radar cfg with
 * the board's cfg dialect and works out which cfg commands would be sent.
 * Opens no serial port and no socket.
 */
static int validate(const std::string& config_file){
    SystemConfigReader cfg(config_file);
    if (!cfg.initialized) {
        //SystemConfigReader already printed the reason
        std::cout << "INVALID: " << config_file << std::endl;
        return 1;
    }
    const cpsl::radar::BoardDescriptor& board = cfg.getBoard();

    RadarConfigReader radar;
    try {
        radar.initialize(cfg.getRadarConfigPath(), board.cfg_dialect.rx_mask_fields,
                         board.cfg_dialect.frame_period_field);
    } catch (const std::exception& e) {
        std::cerr << "radar cfg " << cfg.getRadarConfigPath() << ": cannot parse: " << e.what() << std::endl;
        std::cout << "INVALID: " << config_file << std::endl;
        return 1;
    }
    if (!radar.initialized || radar.get_bytes_per_frame() == 0) {
        std::cerr << "radar cfg " << cfg.getRadarConfigPath() << ": no usable frame shape" << std::endl;
        std::cout << "INVALID: " << config_file << std::endl;
        return 1;
    }

    std::ifstream f(cfg.getRadarConfigPath());
    std::vector<std::string> lines;
    std::string line;
    while (std::getline(f, line)) lines.push_back(line);
    const cpsl::radar::CfgCommandPlan plan = cpsl::radar::filter_cfg_commands(lines, board);

    std::cout << "config:     " << config_file << " (schema v" << SystemConfigReader::kSchemaVersion << ")\n"
              << "board:      " << board.name << " (" << cfg.getBoardPath() << "; sdk "
              << cpsl::radar::to_string(board.sdk) << ")\n"
              << "radar cfg:  " << cfg.getRadarConfigPath() << "\n"
              << "cli:        " << cfg.getRadarCliPort() << " @ " << cfg.getRadarCliBaudRate() << " baud, "
              << cfg.getRadarCliTimeoutMs() << " ms per command\n";
    if (cfg.get_serial_streaming_enabled()) {
        std::cout << "serial:     " << cfg.getRadarDataPort() << " @ " << cfg.getRadarDataBaudRate() << " baud, "
                  << "tlv " << cpsl::radar::to_string(board.data_uart.tlv_dialect) << ", timeout "
                  << cfg.getRadarDataTimeoutMs() << " ms\n";
    } else {
        std::cout << "serial:     off\n";
    }
    if (cfg.get_dca1000_streaming_enabled()) {
        std::cout << "dca1000:    fpga " << cfg.getDCAFpgaIP() << ", host " << cfg.getDCASystemIP() << ", cmd "
                  << cfg.getDCACmdPort() << ", data " << cfg.getDCADataPort() << "; " << board.lvds.lanes
                  << " lanes, " << cpsl::radar::to_string(board.lvds.layout) << ", "
                  << cpsl::radar::to_string(board.lvds.iq_order) << "\n";
    } else {
        std::cout << "dca1000:    off\n";
    }
    std::cout << "frame:      " << radar.get_num_rx_antennas() << " rx x " << radar.get_samples_per_chirp()
              << " samples x " << radar.get_chirps_per_frame() << " chirps, " << radar.get_frame_period_ms()
              << " ms period (cfg fields: rx masks " << join(board.cfg_dialect.rx_mask_fields)
              << ", period " << board.cfg_dialect.frame_period_field << ")\n"
              << "bytes/frame: " << radar.get_bytes_per_frame() << "\n"
              << "output:     " << (cfg.get_output_dir().empty() ? std::string("(current directory)") : cfg.get_output_dir())
              << "; adc frames " << (cfg.get_save_adc_frames() ? "on" : "off") << ", raw lvds "
              << (cfg.get_save_raw_lvds() ? "on" : "off") << "\n"
              << "log level:  " << to_string(cfg.get_log_level()) << "\n"
              << "commands:   " << plan.send.size() << " sent, " << plan.skipped.size() << " skipped\n";
    for (const std::string& c : plan.skipped) {
        std::cout << "skipped:    " << c << " (board skip_commands)\n";
    }
    if (board.lifecycle.config_once_per_boot) {
        std::cout << "note:       " << board.name << " accepts a cfg once per power-up\n";
    }
    for (const std::string& n : cfg.getCfgCheckNotes()) {
        std::cout << "note:       " << n << "\n";
    }
    std::cout << "OK: " << config_file << std::endl;
    return 0;
}

int main(int argc, char* argv[]){

    std::string config_file;
    bool validate_only = false;
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        if (a == "--validate") {
            validate_only = true;
        } else if (a == "-h" || a == "--help") {
            print_usage(argv[0]);
            return 0;
        } else if (!a.empty() && a[0] == '-') {
            std::cerr << "unknown option: " << a << std::endl;
            print_usage(argv[0]);
            return 2;
        } else if (config_file.empty()) {
            config_file = a;
        } else {
            std::cerr << "more than one config given" << std::endl;
            print_usage(argv[0]);
            return 2;
        }
    }
    if (config_file.empty()) {
        print_usage(argv[0]);
        return 2;
    }
    if (validate_only) {
        return validate(config_file);
    }

    //handle sigint commands
    signal(SIGINT,signalHandler);

    std::cout << "Using config: " << config_file << std::endl;

    Runner runner(config_file);
    runner_global = &runner;

    if(runner.initialized){
        int frame_count = 0;
        int timeout_ms = 2000;

        runner.start();

        while(true){
            bool got_frame = false;

            if(runner.get_dca1000_streaming_enabled() &&
                runner.get_next_adc_cube(timeout_ms).size() > 0){
                got_frame = true;
            }

            if(runner.get_serial_streaming_enabled()){
                std::vector<std::vector<float>> points;
                if(runner.get_next_tlv_detected_points(points, timeout_ms)){
                    got_frame = true;
                    std::cout << "TLV frame " << runner.get_latest_tlv_frame_number()
                              << ": " << points.size() << " detected points";
                    if(!points.empty()){
                        std::cout << " (first: x=" << points[0][0] << " y=" << points[0][1]
                                  << " z=" << points[0][2] << " v=" << points[0][3] << ")";
                    }
                    std::cout << std::endl;
                }
            }

            //stop once no stream produces a frame within the timeout
            if(!got_frame){
                break;
            }
            frame_count += 1;
        }

        if(runner.get_serial_streaming_enabled()){
            std::cout << "Received " << frame_count << " frames, "
                      << runner.get_tlv_missed_frame_count() << " missed" << std::endl;
        }

        runner.stop();
    } else{
        std::cerr << "Runner failed to initialize" << std::endl;
        return 1;
    }

    return 0;
}
