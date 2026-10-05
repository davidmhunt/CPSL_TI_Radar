#include "RadarConfig.hpp"

#include <unistd.h>

#include <exception>
#include <filesystem>
#include <fstream>
#include <vector>

namespace cpsl {
namespace radar {

namespace fs = std::filesystem;

const char* to_string(OutputDirCheck::State s) {
    switch (s) {
        case OutputDirCheck::State::current_dir: return "current directory";
        case OutputDirCheck::State::exists: return "exists";
        case OutputDirCheck::State::will_be_created: return "will be created";
        case OutputDirCheck::State::error: return "error";
    }
    return "?";
}

namespace {

bool writable_dir(const fs::path& p) { return ::access(p.c_str(), W_OK | X_OK) == 0; }

}  // namespace

OutputDirCheck check_output_dir(const std::string& dir) {
    OutputDirCheck c;
    c.path = dir;
    if (dir.empty()) {
        c.state = OutputDirCheck::State::current_dir;
        return c;
    }
    std::error_code ec;
    const fs::path p(dir);
    const fs::file_status st = fs::status(p, ec);
    if (fs::exists(st)) {
        if (!fs::is_directory(st)) {
            c.state = OutputDirCheck::State::error;
            c.message = "output.dir " + dir + " exists and is not a directory";
        } else if (!writable_dir(p)) {
            c.state = OutputDirCheck::State::error;
            c.message = "output.dir " + dir + " is not writable";
        } else {
            c.state = OutputDirCheck::State::exists;
        }
        return c;
    }
    // missing: the nearest existing ancestor decides (a path under a regular
    // file stats as "not found", so the walk stops at that file)
    fs::path q = p;
    for (;;) {
        fs::path parent = q.parent_path();
        if (parent.empty()) parent = ".";
        if (parent == q) break;  // reached the root without finding anything
        const fs::file_status pst = fs::status(parent, ec);
        if (fs::exists(pst)) {
            if (!fs::is_directory(pst)) {
                c.state = OutputDirCheck::State::error;
                c.message = "output.dir " + dir + " cannot be created: " + parent.string() + " is a file";
            } else if (!writable_dir(parent)) {
                c.state = OutputDirCheck::State::error;
                c.message = "output.dir " + dir + " cannot be created: " + parent.string() + " is not writable";
            } else {
                c.state = OutputDirCheck::State::will_be_created;
            }
            return c;
        }
        q = parent;
    }
    c.state = OutputDirCheck::State::error;
    c.message = "output.dir " + dir + ": no existing parent directory";
    return c;
}

Status create_output_dir(const std::string& dir) {
    if (dir.empty()) return Status::ok();
    std::error_code ec;
    fs::create_directories(dir, ec);
    if (ec) {
        return Status(Code::output_dir, "cannot create output.dir " + dir + ": " + ec.message());
    }
    if (!fs::is_directory(dir, ec)) {
        return Status(Code::output_dir, "output.dir " + dir + " is not a directory");
    }
    return Status::ok();
}

Result<RadarConfig> RadarConfig::load(const std::string& system_json) {
    try {
        RadarConfig c;
        if (!c.system_.initialize(system_json)) {
            return Status(Code::invalid_config, c.system_.get_error());
        }
        const BoardDescriptor& board = c.system_.getBoard();
        const std::string cfg_path = c.system_.getRadarConfigPath();

        c.radar_.initialize(cfg_path, board.cfg_dialect.rx_mask_fields, board.cfg_dialect.frame_period_field);
        if (!c.radar_.initialized) {
            return Status(Code::invalid_config, "radar cfg " + cfg_path + ": " + c.radar_.get_error());
        }
        if (c.radar_.get_bytes_per_frame() == 0) {
            return Status(Code::invalid_config, "radar cfg " + cfg_path + ": no usable frame shape");
        }
        c.shape_.rx = static_cast<uint32_t>(c.radar_.get_num_rx_antennas());
        c.shape_.samples = static_cast<uint32_t>(c.radar_.get_samples_per_chirp());
        c.shape_.chirps = static_cast<uint32_t>(c.radar_.get_chirps_per_frame());
        c.shape_.bytes = static_cast<uint64_t>(c.radar_.get_bytes_per_frame());
        c.shape_.period_ms = c.radar_.get_frame_period_ms();

        std::ifstream f(cfg_path);
        std::vector<std::string> lines;
        std::string line;
        while (std::getline(f, line)) lines.push_back(line);
        c.commands_ = filter_cfg_commands(lines, board);
        return c;
    } catch (const std::exception& e) {
        return Status(Code::invalid_config, system_json + ": " + e.what());
    } catch (...) {
        return Status(Code::invalid_config, system_json + ": unknown error while loading");
    }
}

}  // namespace radar
}  // namespace cpsl
