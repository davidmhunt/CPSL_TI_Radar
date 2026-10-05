// CPSL_TI_Radar_CPP: the command-line driver, on the public API only
// (cpsl::radar::RadarConfig, Radar, Status; design §3).
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "Radar.hpp"
#include "StopSignal.hpp"

namespace radar = cpsl::radar;
using steady = std::chrono::steady_clock;

static void print_usage(const char* prog){
    std::cerr << "usage: " << prog << " <system.json> [--validate] [--stats] [--frames N] [--duration S]\n"
              << "  <system.json>  system config, schema v2 (v1 files: uv run "
              << SystemConfigReader::kMigrationScript << ")\n"
              << "  --validate     load and cross-check the config (board descriptor, radar cfg, output.dir)\n"
              << "                 without opening any port or socket; exit 0 if it is usable\n"
              << "  --stats        print one 'stats v1' line per stream every second, and a final one\n"
              << "  --frames N     stop after N frames (DCA1000 frames if enabled, else TLV frames)\n"
              << "  --duration S   stop after S seconds of streaming\n"
              << "Without --frames/--duration the run ends on Ctrl-C (SIGINT/SIGTERM), or when no\n"
              << "frame arrives for 2 s (runtime.stall_timeout_ms instead, when it is set)."
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
    radar::Result<radar::RadarConfig> loaded = radar::RadarConfig::load(config_file);
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

// "stats v1" lines (format in docs/ARCHITECTURE.md): cumulative counters
// since start(), t in seconds since start()
static void print_stats(const radar::Radar& r, double t){
    const radar::Stats s = r.stats();
    std::ostringstream o;
    o << std::fixed << std::setprecision(3);
    if (r.dca1000_enabled()) {
        o << "stats v1 dca t=" << t << " frames=" << s.frames << " packets=" << s.packets
          << " dropped=" << s.dropped << " drop_events=" << s.drop_events << " late=" << s.late
          << " duplicate=" << s.duplicate << " incomplete=" << s.incomplete_frames
          << " skipped=" << s.skipped_frames << " overrun=" << s.rx_overrun
          << " overwritten=" << s.frames_overwritten << " stalls=" << s.stalls
          << " rcvbuf=" << s.rcvbuf_bytes << "\n";
    }
    if (r.serial_enabled()) {
        o << "stats v1 serial t=" << t << " frames=" << s.serial_frames << " missed=" << s.serial_missed
          << " overwritten=" << s.serial_overwritten << " stalls=" << s.stalls << "\n";
    }
    std::cout << o.str() << std::flush;
}

static bool parse_count(const std::string& text, uint64_t& out){
    char* end = nullptr;
    const unsigned long long v = std::strtoull(text.c_str(), &end, 10);
    if (text.empty() || text[0] == '-' || *end != '\0' || v == 0) return false;
    out = v;
    return true;
}

static bool parse_seconds(const std::string& text, double& out){
    char* end = nullptr;
    const double v = std::strtod(text.c_str(), &end);
    if (text.empty() || *end != '\0' || !(v > 0)) return false;
    out = v;
    return true;
}

int main(int argc, char* argv[]){

    std::string config_file;
    bool validate_only = false;
    bool stats = false;
    uint64_t max_frames = 0;      // 0 = no limit
    double max_seconds = 0;       // 0 = no limit
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        if (a == "--validate") {
            validate_only = true;
        } else if (a == "--stats") {
            stats = true;
        } else if (a == "--frames" || a == "--duration") {
            const bool ok = i + 1 < argc && (a == "--frames" ? parse_count(argv[i + 1], max_frames)
                                                             : parse_seconds(argv[i + 1], max_seconds));
            if (!ok) {
                std::cerr << a << " needs a positive " << (a == "--frames" ? "integer" : "number") << std::endl;
                print_usage(argv[0]);
                return 2;
            }
            i++;
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
    if(!radar::install_stop_signal_handlers()){
        std::cerr << "warning: could not install the SIGINT/SIGTERM handler" << std::endl;
    }

    std::cout << "Using config: " << config_file << std::endl;

    radar::Result<radar::RadarConfig> cfg = radar::RadarConfig::load(config_file);
    if (!cfg) {
        std::cerr << "error: " << cfg.status.message << std::endl;
        return 1;
    }
    radar::Result<std::unique_ptr<radar::Radar>> opened = radar::Radar::open(*cfg);
    if (!opened) {
        std::cerr << "error: " << opened.status.message << std::endl;
        return 1;
    }
    radar::Radar& r = **opened;
    const radar::BoardDescriptor& board = cfg->board();

    //a Ctrl-C before or while the config is sent: don't start streaming
    if (!radar::stop_requested()) {
        const radar::Status s = r.configure();
        //a non-ack is fatal only on a board that accepts one cfg per power-up
        if (!s && !(s.code == radar::Code::config_rejected && !board.lifecycle.config_once_per_boot)) {
            std::cerr << "error: " << s.message << std::endl;
            r.stop();
            return 1;
        }
        if (!s) {
            std::cerr << "warning: " << s.message << std::endl;
        }
    }
    if (!radar::stop_requested()) {
        const radar::Status s = r.start();
        if (!s) {
            std::cerr << "error: " << s.message << std::endl;
            r.stop();
            return 1;
        }
    }

    const bool dca = r.dca1000_enabled();
    const bool serial = r.serial_enabled();
    const uint32_t stall_ms = cfg->system().get_stall_timeout_ms();
    //wait per stream per loop: short enough for 1 Hz stats and a quick Ctrl-C
    const std::chrono::milliseconds wait(dca && serial ? 20 : 100);
    const steady::time_point t_start = steady::now();
    steady::time_point last_frame = t_start;
    steady::time_point next_stats = t_start + std::chrono::seconds(1);
    uint64_t tlv_frames = 0;
    radar::AdcFrame frame;
    radar::PointCloud cloud;

    while (!radar::stop_requested()) {
        bool got_frame = false;
        bool stalled = false;
        radar::Status why;

        if (dca) {
            if (r.next_adc_frame(frame, wait, &why)) {
                got_frame = true;
            } else if (why.code == radar::Code::stalled) {
                stalled = true;
            }
        }
        if (serial) {
            if (r.next_point_cloud(cloud, wait, &why)) {
                got_frame = true;
                tlv_frames += 1;
                std::cout << "TLV frame " << cloud.frame_number << ": " << cloud.points.size() << " detected points";
                if (!cloud.points.empty()) {
                    const radar::Point& p = cloud.points[0];
                    std::cout << " (first: x=" << p.x << " y=" << p.y << " z=" << p.z << " v=" << p.v << ")";
                }
                std::cout << std::endl;
            } else if (why.code == radar::Code::stalled) {
                stalled = true;
            }
        }

        const steady::time_point now = steady::now();
        if (got_frame) last_frame = now;
        if (stats && now >= next_stats) {
            print_stats(r, std::chrono::duration<double>(now - t_start).count());
            while (next_stats <= now) next_stats += std::chrono::seconds(1);
        }
        if (max_frames > 0) {
            const radar::Stats st = r.stats();
            if ((dca ? st.frames : st.serial_frames) >= max_frames) {
                std::cerr << "--frames " << max_frames << " reached, stopping" << std::endl;
                break;
            }
        }
        if (max_seconds > 0 && std::chrono::duration<double>(now - t_start).count() >= max_seconds) {
            std::cerr << "--duration " << max_seconds << " s reached, stopping" << std::endl;
            break;
        }
        if (stall_ms > 0) {
            if (stalled) {
                std::cerr << "no frame for " << stall_ms << " ms (runtime.stall_timeout_ms), stopping" << std::endl;
                break;
            }
        } else if (now - last_frame >= std::chrono::seconds(2)) {
            std::cerr << "no frame for 2 s, stopping" << std::endl;
            break;
        }
    }

    if (serial) {
        std::cout << "Received " << tlv_frames << " frames, " << r.stats().serial_missed << " missed" << std::endl;
    }
    if (radar::stop_requested()) {
        std::cout << "Stop requested (SIGINT/SIGTERM), stopping" << std::endl;
    }
    //non-zero if the stop hit an I/O error (e.g. the radar's USB was unplugged)
    //or an output file failed to flush; the files are closed either way
    const radar::Status stopped = r.stop();
    if (stats) {
        print_stats(r, std::chrono::duration<double>(steady::now() - t_start).count());
    }
    if (!stopped) {
        std::cerr << "stopped with errors: " << stopped.message << std::endl;
        return 1;
    }
    return 0;
}
