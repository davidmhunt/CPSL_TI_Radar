#ifndef CPSL_RADAR_RADAR_CONFIG_HPP
#define CPSL_RADAR_RADAR_CONFIG_HPP

// RadarConfig (driver v2 design §3): one validated run configuration, made of
// the system config (schema v2), its board descriptor (with board_overrides)
// and the parsed radar .cfg. load() never throws and prints nothing; a
// problem comes back as a Status naming the file and JSON path or cfg line.
//
// output.dir is checked separately (output_dir_check(), used by --validate)
// because it depends on the filesystem, not on the files: Radar::open creates
// the directory and fails with Code::output_dir if it cannot.

#include <cstdint>
#include <string>

#include "BoardDescriptor.hpp"
#include "RadarConfigReader.hpp"
#include "Status.hpp"
#include "SystemConfigReader.hpp"

namespace cpsl {
namespace radar {

// One radar frame, from the radar .cfg.
struct FrameShape {
    uint32_t rx = 0;          // receive antennas
    uint32_t samples = 0;     // ADC samples per chirp
    uint32_t chirps = 0;      // chirps per frame
    uint64_t bytes = 0;       // bytes per frame on the DCA1000 stream (4 * rx * samples * chirps)
    float period_ms = 0.0f;   // frameCfg period
};

// Where output.dir stands on this machine.
struct OutputDirCheck {
    enum class State {
        current_dir,      // output.dir unset: files go to the working directory
        exists,           // a writable directory
        will_be_created,  // missing; its nearest existing parent is a writable directory
        error,            // a component is a file, or the directory/parent is not writable
    };
    State state = State::current_dir;
    std::string path;     // output.dir as resolved against the JSON file ("" when unset)
    std::string message;  // for error: what is wrong, naming the path
};
const char* to_string(OutputDirCheck::State s);

// Inspect `dir` without changing anything (stat/access only).
OutputDirCheck check_output_dir(const std::string& dir);
// Create `dir` and its parents (std::filesystem::create_directories); ok if it exists.
Status create_output_dir(const std::string& dir);

class RadarConfig {
public:
    static Result<RadarConfig> load(const std::string& system_json);

    const BoardDescriptor& board() const { return system_.getBoard(); }
    const FrameShape& frame_shape() const { return shape_; }

    // The underlying readers (the driver's internals use them directly).
    const SystemConfigReader& system() const { return system_; }
    const RadarConfigReader& radar_cfg() const { return radar_; }
    // The driver's --skip-configure: same as runtime.skip_configure = true in the system JSON.
    void set_skip_configure(bool v) { system_.set_skip_configure(v); }
    // The cfg commands configure() sends, and the ones the board skips.
    const CfgCommandPlan& commands() const { return commands_; }

    const std::string& path() const { return system_.get_json_file_path(); }
    OutputDirCheck output_dir_check() const { return check_output_dir(system_.get_output_dir()); }

private:
    RadarConfig() = default;

    SystemConfigReader system_;
    RadarConfigReader radar_;
    CfgCommandPlan commands_;
    FrameShape shape_;
};

}  // namespace radar
}  // namespace cpsl

#endif
