// bench_latency: frame complete -> Radar::next_adc_frame return latency
// (directive core-14 P7), hardware-free.
//
// A Radar runs over fake transports: a ReplayPacketSource stands in for the
// DCA1000 and a scripted CLI answers every cfg command with "Done". The main
// thread queues one frame every --period-ms; a consumer thread waits in
// next_adc_frame() and records steady_clock::now() - AdcFrame::completed_at
// (completed_at is taken when the worker has converted the frame, just before
// it is published). Prints the median, p90, p99 and max in microseconds.
//
// Usage: bench_latency [--cfg <radar .cfg>] [--frames N] [--period-ms N]
#include <stdlib.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
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

// the DCA1000 packets of frame `index` (1462-byte payloads)
std::vector<std::vector<uint8_t>> frame_packets(uint64_t index, uint64_t bytes_per_frame, uint32_t& seq) {
    const uint64_t payload = 1462;
    std::vector<std::vector<uint8_t>> out;
    const uint64_t start = index * bytes_per_frame;
    for (uint64_t off = start; off < start + bytes_per_frame; off += payload) {
        const size_t len = static_cast<size_t>(std::min<uint64_t>(payload, start + bytes_per_frame - off));
        std::vector<uint8_t> p(10 + len, static_cast<uint8_t>(index));
        for (int i = 0; i < 4; i++) p[i] = static_cast<uint8_t>(seq >> (8 * i));
        for (int i = 0; i < 6; i++) p[4 + i] = static_cast<uint8_t>(off >> (8 * i));
        out.push_back(std::move(p));
        seq++;
    }
    return out;
}

double pct(std::vector<double> v, double q) {
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    const size_t i = std::min(v.size() - 1, static_cast<size_t>(q * (v.size() - 1) + 0.5));
    return v[i];
}

}  // namespace

int main(int argc, char** argv) {
    std::string cfg = std::string(CONFIG_DIR) + "/radar/nav_configs/1843_stress_test.cfg";
    size_t frames = 200;
    int period_ms = 20;
    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        if (a == "--cfg" && i + 1 < argc) cfg = argv[++i];
        else if (a == "--frames" && i + 1 < argc) frames = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--period-ms" && i + 1 < argc) period_ms = std::atoi(argv[++i]);
        else {
            std::fprintf(stderr, "usage: %s [--cfg <radar .cfg>] [--frames N] [--period-ms N]\n", argv[0]);
            return 2;
        }
    }
    setenv("CPSL_TI_RADAR_BOARDS_DIR", (std::string(CONFIG_DIR) + "/boards").c_str(), 0);
    std::string dir = (std::filesystem::temp_directory_path() / "bench_latency_XXXXXX").string();
    if (mkdtemp(&dir[0]) == nullptr) return 1;
    const std::string json = dir + "/system.json";
    std::ofstream(json) << "{\"schema_version\": 2, \"board\": \"IWR1843\", \"firmware\": \"demo\", \"radar_cfg\": \"" << cfg
                        << "\", \"cli\": {\"port\": \"/dev/null-not-opened\"}, \"dca1000\": {\"enabled\": true, "
                           "\"fpga_ip\": \"127.0.0.1\", \"host_ip\": \"127.0.0.1\", \"cmd_port\": 4096, "
                           "\"data_port\": 4098}, \"output\": {\"dir\": \""
                        << dir << "\", \"save_adc_frames\": false, \"save_raw_lvds\": false}, "
                        << "\"runtime\": {\"log_level\": \"warn\", \"firmware_check\": \"off\"}}";
    Result<RadarConfig> rc = RadarConfig::load(json);
    if (!rc) {
        std::fprintf(stderr, "%s\n", rc.status.message.c_str());
        return 1;
    }
    auto packets = std::make_shared<ReplayPacketSource>();
    Result<std::unique_ptr<Radar>> opened = Radar::open(*rc, {std::make_shared<DoneCli>(), packets});
    if (!opened) {
        std::fprintf(stderr, "%s\n", opened.status.message.c_str());
        return 1;
    }
    Radar& r = **opened;
    if (!r.configure() || !r.start()) {
        std::fprintf(stderr, "configure/start failed\n");
        return 1;
    }
    const uint64_t B = rc->frame_shape().bytes;

    std::vector<double> lat_us;
    lat_us.reserve(frames);
    std::atomic<bool> done{false};
    std::thread consumer([&] {
        AdcFrame f;
        while (!done.load() || lat_us.size() < frames) {
            if (r.next_adc_frame(f, std::chrono::milliseconds(500))) {
                lat_us.push_back(std::chrono::duration<double, std::micro>(clk::now() - f.completed_at).count());
                if (lat_us.size() >= frames) break;
            } else if (done.load()) {
                break;
            }
        }
    });
    uint32_t seq = 1;
    clk::time_point next = clk::now();
    for (size_t k = 0; k < frames; k++) {
        std::this_thread::sleep_until(next);
        next += std::chrono::milliseconds(period_ms);
        for (auto& p : frame_packets(k, B, seq)) packets->push(std::move(p));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    done = true;
    consumer.join();
    const Stats st = r.stats();
    r.stop();
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);

    std::printf("bench_latency: %zu frames of %llu B every %d ms; received %zu, overwritten %llu\n", frames,
                static_cast<unsigned long long>(B), period_ms, lat_us.size(),
                static_cast<unsigned long long>(st.frames_overwritten));
    std::printf("  frame complete -> next_adc_frame return, us: median %.1f  p90 %.1f  p99 %.1f  max %.1f\n",
                pct(lat_us, 0.5), pct(lat_us, 0.9), pct(lat_us, 0.99), pct(lat_us, 1.0));
    return lat_us.size() == frames ? 0 : 1;
}
