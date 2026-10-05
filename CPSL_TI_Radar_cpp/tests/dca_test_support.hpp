// Hardware-free DCA1000Handler fixtures: a schema v2 system config with the
// DCA1000 enabled (nothing is opened: tests call configure_pipeline(), never
// initialize()) and synthetic DCA1000 UDP packets.
#ifndef DCA_TEST_SUPPORT_HPP
#define DCA_TEST_SUPPORT_HPP

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include "SystemConfigReader.hpp"

namespace dca_test {

inline const std::string& tmp_dir() {
    static const std::string d = TEST_TMP_DIR;
    return d;
}

// Writes <tmp>/<name>.json for an IWR1843 + DCA1000 run of tests/data/radar/iwr1843.cfg
// (4 rx x 63 samples x 230 chirps, 231840 B/frame) with output.dir = <out_dir>.
// The host side is always 127.0.0.1; a loopback fake DCA1000 can sit on
// another 127.x address (fpga_ip).
inline std::string write_system_config(const std::string& name, const std::string& out_dir, bool save_adc_frames,
                                       const std::string& fpga_ip = "127.0.0.1", int cmd_port = 4096,
                                       int data_port = 4098) {
    setenv(SystemConfigReader::kBoardsDirEnv, (std::string(CONFIG_DIR) + "/boards").c_str(), 1);
    nlohmann::json j = nlohmann::json::parse(R"({
        "schema_version": 2,
        "board": "IWR1843",
        "radar_cfg": "",
        "cli": { "port": "/dev/null-not-opened" },
        "dca1000": { "enabled": true, "fpga_ip": "127.0.0.1", "host_ip": "127.0.0.1",
                     "cmd_port": 4096, "data_port": 4098 },
        "output": { "dir": "", "save_adc_frames": false, "save_raw_lvds": false }
    })");
    j["radar_cfg"] = std::string(TEST_DATA_DIR) + "/radar/iwr1843.cfg";
    j["dca1000"]["fpga_ip"] = fpga_ip;
    j["dca1000"]["cmd_port"] = cmd_port;
    j["dca1000"]["data_port"] = data_port;
    j["output"]["dir"] = out_dir;
    j["output"]["save_adc_frames"] = save_adc_frames;
    const std::string path = tmp_dir() + "/" + name + ".json";
    std::ofstream(path) << j.dump(2);
    return path;
}

// The packets of frame `index` (1462-byte payloads, as the DCA1000 sends with
// 1472-byte packets). Every 16-bit word of the frame is `tag`, so every
// converted sample is (tag, tag) whatever the lane layout: a cube mixing two
// frames is visible as a mixed value. `seq` is advanced per packet.
inline std::vector<std::vector<uint8_t>> frame_packets(uint64_t index, size_t bytes_per_frame, uint16_t tag,
                                                      uint32_t& seq) {
    const size_t payload = 1462;
    std::vector<std::vector<uint8_t>> out;
    const uint64_t start = index * bytes_per_frame;
    for (uint64_t off = start; off < start + bytes_per_frame; off += payload) {
        const size_t len = static_cast<size_t>(std::min<uint64_t>(payload, start + bytes_per_frame - off));
        std::vector<uint8_t> p(10 + len);
        for (int i = 0; i < 4; i++) p[i] = static_cast<uint8_t>(seq >> (8 * i));
        for (int i = 0; i < 6; i++) p[4 + i] = static_cast<uint8_t>(off >> (8 * i));
        for (size_t k = 0; k < len; k++) {
            // the stream is word aligned (bytes_per_frame is a multiple of 4)
            p[10 + k] = static_cast<uint8_t>(((off + k) % 2 == 0) ? (tag & 0xFF) : (tag >> 8));
        }
        out.push_back(std::move(p));
        seq++;
    }
    return out;
}

}  // namespace dca_test

#endif  // DCA_TEST_SUPPORT_HPP
