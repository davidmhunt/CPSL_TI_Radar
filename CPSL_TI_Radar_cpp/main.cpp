//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <csignal>
#include <exception>
#include <fstream>
#include <vector>

//JSON handling
#include "RadarConfig.hpp"
#include "Runner.hpp"
#include "StopSignal.hpp"

using json = nlohmann::json;

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
 * RadarConfig::load reads the system config (resolving the board descriptor
 * with its board_overrides and running cross_check_radar_cfg), parses the
 * radar cfg with the board's cfg dialect and works out which cfg commands
 * would be sent; output.dir is checked on the filesystem (exists / will be
 * created / error). Opens no serial port and no socket.
 */
static int validate(const std::string& config_file){
    cpsl::radar::Result<cpsl::radar::RadarConfig> loaded = cpsl::radar::RadarConfig::load(config_file);
    if (!loaded) {
        std::cerr << loaded.status.message << std::endl;
        std::cout << "INVALID: " << config_file << std::endl;
        return 1;
    }
    const cpsl::radar::RadarConfig& rc = *loaded;
    const SystemConfigReader& cfg = rc.system();
    const cpsl::radar::BoardDescriptor& board = rc.board();
    const cpsl::radar::FrameShape& shape = rc.frame_shape();
    const cpsl::radar::CfgCommandPlan& plan = rc.commands();
    const cpsl::radar::OutputDirCheck out = rc.output_dir_check();

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
    std::cout << "frame:      " << shape.rx << " rx x " << shape.samples
              << " samples x " << shape.chirps << " chirps, " << shape.period_ms
              << " ms period (cfg fields: rx masks " << join(board.cfg_dialect.rx_mask_fields)
              << ", period " << board.cfg_dialect.frame_period_field << ")\n"
              << "bytes/frame: " << shape.bytes << "\n"
              << "output:     "
              << (out.path.empty() ? std::string("(current directory)")
                                   : out.path + " (" + cpsl::radar::to_string(out.state) + ")")
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
    if (out.state == cpsl::radar::OutputDirCheck::State::error) {
        std::cerr << out.message << std::endl;
        std::cout << "INVALID: " << config_file << std::endl;
        return 1;
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

    //SIGINT/SIGTERM only set a flag; the loop below sees it and stops cleanly
    //(threads joined, sensorStop/recordStop sent, output files flushed and closed)
    if(!cpsl::radar::install_stop_signal_handlers()){
        std::cerr << "warning: could not install the SIGINT/SIGTERM handler" << std::endl;
    }

    std::cout << "Using config: " << config_file << std::endl;

    Runner runner(config_file);

    if(runner.initialized){
        int frame_count = 0;
        int timeout_ms = 2000;

        //a Ctrl-C while the config was being sent: don't start streaming
        if(!cpsl::radar::stop_requested()){
            runner.start();
        }

        while(!cpsl::radar::stop_requested()){
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
            //(a stop request during the wait is checked by the loop condition)
            if(!got_frame && !cpsl::radar::stop_requested()){
                break;
            }
            if(got_frame){
                frame_count += 1;
            }
        }

        if(runner.get_serial_streaming_enabled()){
            std::cout << "Received " << frame_count << " frames, "
                      << runner.get_tlv_missed_frame_count() << " missed" << std::endl;
        }

        if(cpsl::radar::stop_requested()){
            std::cout << "Stop requested (SIGINT/SIGTERM), stopping" << std::endl;
        }
        //non-zero if the stop hit an I/O error (e.g. the radar's USB was unplugged);
        //the output files are closed either way
        if(!runner.stop()){
            std::cerr << "stopped with errors (see above)" << std::endl;
            return 1;
        }
    } else{
        std::cerr << "Runner failed to initialize" << std::endl;
        return 1;
    }

    return 0;
}
