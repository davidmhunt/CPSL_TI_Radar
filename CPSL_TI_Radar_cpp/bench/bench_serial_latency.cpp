// bench_serial_latency: serial TLV frame latency over a pty (directive core-16
// P8), hardware-free.
//
// A Radar runs with serial streaming on. Its data port is the slave side of a
// pseudo-terminal (the real SerialPortStream path: open, termios, poll, read);
// the CLI is a scripted fake that answers every command with "Done". The main
// thread writes one SDK 3 frame (40-byte header, TLV 1 points, TLV 7 side
// info, padded to a multiple of 32 bytes) to the pty master every period. A
// consumer thread waits in next_point_cloud() and timestamps each return.
//
// For frame k it reports:
//   latency = next_point_cloud returned frame k - last byte of frame k written
// and checks that frame k was returned before the first byte (the magic word)
// of frame k+1 was written. A reader that frames on the NEXT magic word fails
// that check by construction: it delivers each frame one period late.
//
// Usage: bench_serial_latency [--cfg <radar .cfg>] [--frames N] [--period-ms N] [--points N]
//   --period-ms defaults to the cfg's frameCfg period. Exit 0 only if every
//   frame arrived, each before the next frame's magic word.
#include <pty.h>
#include <stdlib.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "Radar.hpp"

namespace {

using namespace cpsl::radar;
using clk = std::chrono::steady_clock;

// answers every written line with its echo, "Done" and the demo prompt
class DoneCli : public ByteStream {
public:
    std::error_code write(const uint8_t* data, size_t len, std::chrono::milliseconds) override {
        std::lock_guard<std::mutex> l(m_);
        std::string cmd(reinterpret_cast<const char*>(data), len);
        if (!cmd.empty() && cmd.back() == '\n') cmd.pop_back();
        pending_ += "\r\n" + cmd + "\r\nDone\r\nmmwDemo:/>";
        return {};
    }
    std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) override {
        n = 0;
        {
            std::lock_guard<std::mutex> l(m_);
            if (!pending_.empty()) {
                n = std::min(cap, pending_.size());
                std::memcpy(buf, pending_.data(), n);
                pending_.erase(0, n);
                return {};
            }
        }
        std::this_thread::sleep_for(std::min(timeout, std::chrono::milliseconds(1)));
        return std::make_error_code(std::errc::timed_out);
    }

private:
    std::mutex m_;
    std::string pending_;
};

void put_u32(std::vector<uint8_t>& b, uint32_t v) {
    for (int i = 0; i < 4; i++) b.push_back(static_cast<uint8_t>(v >> (8 * i)));
}

// one SDK 3 frame: header, TLV 1 (n points), TLV 7 (n side-info pairs), zero pad to 32
std::vector<uint8_t> sdk3_frame(uint32_t frame_number, uint32_t n) {
    std::vector<uint8_t> body;
    put_u32(body, 1);
    put_u32(body, 16 * n);
    for (uint32_t i = 0; i < 4 * n; i++) {
        float f = static_cast<float>(i) * 0.25f;
        uint32_t u;
        std::memcpy(&u, &f, 4);
        put_u32(body, u);
    }
    put_u32(body, 7);
    put_u32(body, 4 * n);
    for (uint32_t i = 0; i < n; i++) put_u32(body, 0x00C80064u);  // snr 10.0 dB, noise 20.0 dB
    size_t total = 40 + body.size();
    total = (total + 31) / 32 * 32;
    std::vector<uint8_t> f = {2, 1, 4, 3, 6, 5, 8, 7};
    put_u32(f, 0x03060000);  // version
    put_u32(f, static_cast<uint32_t>(total));
    put_u32(f, 0x000A1843);  // platform
    put_u32(f, frame_number);
    put_u32(f, 0);           // timeCpuCycles
    put_u32(f, n);           // numDetectedObj
    put_u32(f, 2);           // numTLVs
    put_u32(f, 0);           // subFrameNumber
    f.insert(f.end(), body.begin(), body.end());
    f.resize(total, 0);
    return f;
}

double pct(std::vector<double> v, double q) {
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    const size_t i = std::min(v.size() - 1, static_cast<size_t>(q * (v.size() - 1) + 0.5));
    return v[i];
}

}  // namespace

int main(int argc, char** argv) {
    std::string cfg = std::string(CONFIG_DIR) + "/radar/IWR1843/demo/stress_test.cfg";
    size_t frames = 100;
    int period_ms = 0;
    uint32_t points = 20;
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        if (a == "--cfg" && i + 1 < argc) cfg = argv[++i];
        else if (a == "--frames" && i + 1 < argc) frames = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--period-ms" && i + 1 < argc) period_ms = std::atoi(argv[++i]);
        else if (a == "--points" && i + 1 < argc) points = static_cast<uint32_t>(std::strtoul(argv[++i], nullptr, 10));
        else {
            std::fprintf(stderr, "usage: %s [--cfg <radar .cfg>] [--frames N] [--period-ms N] [--points N]\n",
                         argv[0]);
            return 2;
        }
    }

    int master = -1, slave = -1;
    char name[256] = {0};
    if (openpty(&master, &slave, name, nullptr, nullptr) != 0) {
        std::perror("openpty");
        return 1;
    }

    setenv("CPSL_TI_RADAR_BOARDS_DIR", (std::string(CONFIG_DIR) + "/boards").c_str(), 0);
    std::string dir = (std::filesystem::temp_directory_path() / "bench_serial_latency_XXXXXX").string();
    if (mkdtemp(&dir[0]) == nullptr) return 1;
    const std::string json = dir + "/system.json";
    std::ofstream(json) << "{\"schema_version\": 2, \"board\": \"IWR1843\", \"firmware\": \"demo\", \"radar_cfg\": \"" << cfg
                        << "\", \"cli\": {\"port\": \"/dev/null-not-opened\"}, "
                        << "\"serial_stream\": {\"enabled\": true, \"port\": \"" << name << "\"}, "
                        << "\"dca1000\": {\"enabled\": false}, "
                        << "\"output\": {\"dir\": \"" << dir << "\", \"save_adc_frames\": false, "
                        << "\"save_raw_lvds\": false}, \"runtime\": {\"log_level\": \"warn\", \"firmware_check\": \"off\"}}";
    Result<RadarConfig> rc = RadarConfig::load(json);
    if (!rc) {
        std::fprintf(stderr, "%s\n", rc.status.message.c_str());
        return 1;
    }
    if (period_ms <= 0) period_ms = static_cast<int>(rc->frame_shape().period_ms + 0.5f);
    Transports tr;
    tr.cli = std::make_shared<DoneCli>();
    Result<std::unique_ptr<Radar>> opened = Radar::open(*rc, tr);
    if (!opened) {
        std::fprintf(stderr, "%s\n", opened.status.message.c_str());
        return 1;
    }
    Radar& r = **opened;
    if (!r.configure() || !r.start()) {
        std::fprintf(stderr, "configure/start failed\n");
        return 1;
    }

    std::vector<clk::time_point> write_start(frames), write_end(frames);
    std::mutex rm;
    std::map<uint32_t, clk::time_point> received;  // frame number -> next_point_cloud return
    size_t bad_points = 0;
    std::atomic<bool> done{false};
    std::thread consumer([&] {
        PointCloud pc;
        while (!done.load()) {
            if (r.next_point_cloud(pc, std::chrono::milliseconds(100))) {
                const clk::time_point t = clk::now();
                std::lock_guard<std::mutex> l(rm);
                received.emplace(pc.frame_number, t);
                if (pc.points.size() != points) bad_points++;
            }
        }
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(100));  // reader running
    clk::time_point next = clk::now();
    for (size_t k = 0; k < frames; k++) {
        const std::vector<uint8_t> f = sdk3_frame(static_cast<uint32_t>(k + 1), points);
        std::this_thread::sleep_until(next);
        next += std::chrono::milliseconds(period_ms);
        write_start[k] = clk::now();
        size_t off = 0;
        while (off < f.size()) {
            const ssize_t w = ::write(master, f.data() + off, f.size() - off);
            if (w <= 0) break;
            off += static_cast<size_t>(w);
        }
        write_end[k] = clk::now();
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(2 * period_ms + 100));
    done = true;
    consumer.join();
    r.stop();
    close(master);
    close(slave);
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);

    std::vector<double> lat_us;
    size_t missing = 0, late = 0;
    for (size_t k = 0; k < frames; k++) {
        auto it = received.find(static_cast<uint32_t>(k + 1));
        if (it == received.end()) {
            missing++;
            continue;
        }
        lat_us.push_back(std::chrono::duration<double, std::micro>(it->second - write_end[k]).count());
        if (k + 1 < frames && it->second >= write_start[k + 1]) late++;
    }
    std::printf("bench_serial_latency: %zu frames of %u points every %d ms over %s; received %zu, missing %zu, "
                "late (after the next magic word) %zu, wrong point count %zu\n",
                frames, points, period_ms, name, lat_us.size(), missing, late, bad_points);
    std::printf("  last byte written -> next_point_cloud return, us: median %.1f  p90 %.1f  p99 %.1f  max %.1f\n",
                pct(lat_us, 0.5), pct(lat_us, 0.9), pct(lat_us, 0.99), pct(lat_us, 1.0));
    return (missing == 0 && late == 0 && bad_points == 0) ? 0 : 1;
}
