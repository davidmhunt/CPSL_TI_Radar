// bench_pipeline: hardware-free replay benchmark of the DCA1000 raw-ADC path
// (driver v2 design §5, directive core-09).
//
// Replays synthetic DCA1000 UDP packets through the driver's FrameAssembler and an
// ADC converter, and reports frames/s, CPU ns per ADC byte and heap
// allocations per frame (counting global operator new). The converter is
// pluggable so the D5 question (nested vs flat AdcFrame) can be revisited
// with data; see converter_kernels.hpp for the three variants.
//
// Three measurements:
//   1. converter only: the same assembled frame converted N times, for all
//      three variants on identical input
//   2. pipeline replay: FrameAssembler + converter over a packet stream, for
//      three scenarios (clean, 1% dropped packets, duplicates + reordering),
//      again for all three variants
//   3. driver replay (rows "drv_*", variant (d)), added for the core-14 perf
//      gate: the same kind of packet stream through the driver's own
//      DCA1000Handler (configure_pipeline + ingest_packet: assembler,
//      converter, publish, adc_data.bin), as the DCA worker thread runs it.
//      drv_save writes adc_data.bin to a temp dir (--tmp-dir, default
//      /dev/shm when present, so disk writeback does not add noise). Driver
//      log messages go to a counting sink at --log-level (default info).
//
// Every rep runs the variants in turn (a, b, c, a, b, c, ...) after one
// untimed warm-up rep; the table shows the median rep and, in brackets, the
// best rep. Single-threaded; no sockets.
//
// Compare two builds with tools/bench/pipeline_gate.py (the perf gate).
//
// --udp (loopback mode, directive core-15) replaces the three measurements
// above with one run of the real RX path: a sender thread replays the clean
// synthetic stream over 127.0.0.1 into a real DCA1000Socket (its RX thread
// and packet ring), and a worker thread runs DCA1000Handler::process_next_packet
// as Radar's DCA worker does. No DCA1000 command is sent. It prints one
// "udp ..." key=value row: frames (golden or not), packets sent / delivered,
// user-space discards (the socket's overrun count), kernel drops (the
// socket's drops column in /proc/net/udp), CPU ns per payload byte and
// context switches of the RX + worker threads (getrusage, minus the sender
// and main threads). --stall-ms N stalls the worker once at frame N/2 (or
// every --stall-every K frames) to model a slow consumer. --rx-cpu and
// --worker-cpu pin the two threads as runtime.rx_cpu / worker_cpu do.
//
// Usage: bench_pipeline [--cfg <radar .cfg>] [--frames N] [--reps N]
//                       [--log-level error|warn|info|debug] [--tmp-dir DIR]
//        bench_pipeline --udp [--cfg <radar .cfg>] [--frames N] [--udp-rate PKT_PER_S|max]
//                       [--stall-ms N [--stall-every K]] [--udp-rcvbuf BYTES]
//                       [--rx-cpu N] [--worker-cpu N]
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <new>
#include <streambuf>
#include <string>
#include <thread>
#include <vector>

#include "DCA1000Handler.hpp"
#include "DCA1000Socket.hpp"
#include "ThreadPlacement.hpp"
#include "FrameAssembler.hpp"
#include "Log.hpp"
#include "RadarConfigReader.hpp"
#include "SystemConfigReader.hpp"
#include "converter_kernels.hpp"

// ---------------------------------------------------------------------------
// Counting allocator (atomic: --udp runs the driver's RX and worker threads)
// ---------------------------------------------------------------------------
static std::atomic<uint64_t> g_allocs{0};

void* operator new(std::size_t n) {
    g_allocs.fetch_add(1, std::memory_order_relaxed);
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](std::size_t n) {
    g_allocs.fetch_add(1, std::memory_order_relaxed);
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }

namespace {

using bench::FrameShape;
using bench::Kernel;
using Clock = std::chrono::steady_clock;

// keep the compiler from discarding a kernel's output
inline void escape(const void* p) { asm volatile("" : : "g"(p) : "memory"); }

// swallows anything printed to std::cout while the radar cfg is read and
// during timed sections (the driver itself logs through the log sink only)
class NullBuf : public std::streambuf {
protected:
    int overflow(int c) override { return c; }
    std::streamsize xsputn(const char*, std::streamsize n) override { return n; }
};

struct Rng {  // xorshift64*, deterministic
    uint64_t s;
    explicit Rng(uint64_t seed) : s(seed) {}
    uint64_t next() {
        s ^= s >> 12;
        s ^= s << 25;
        s ^= s >> 27;
        return s * 2685821657736338717ULL;
    }
    double uniform() { return (next() >> 11) * (1.0 / 9007199254740992.0); }
};

// A replayable packet stream: one contiguous buffer plus per-packet offsets.
struct PacketStream {
    std::string name;
    std::vector<uint8_t> buf;
    std::vector<size_t> off, len;
    uint64_t payload_bytes = 0;  // ADC bytes fed to the assembler
    size_t dropped = 0, duplicated = 0, swapped = 0;
};

const size_t kPacketBytes = 1472;  // DCA1000Handler: udp_packet_size = 1472
const size_t kHeader = 10;

// Build the in-order packet sequence covering `frames` frames, then inject
// drops / duplicates / adjacent swaps with the given per-packet probabilities.
// `tail_packets` clean packets of frame `frames` follow (never emitted): they
// move the stream past the reorder slack, so the last frame closes without
// FrameAssembler::flush() (the driver rows have no flush).
PacketStream make_stream(const std::string& name, size_t bytes_per_frame, size_t frames, double p_drop,
                         double p_dup, double p_swap, uint64_t seed, size_t tail_packets = 0) {
    const size_t payload = kPacketBytes - kHeader;
    const uint64_t total = static_cast<uint64_t>(bytes_per_frame) * frames;
    const size_t n = static_cast<size_t>((total + payload - 1) / payload);

    // the in-order stream as (seq, byte offset, length) triples
    struct Pkt {
        uint32_t seq;
        uint64_t offset;
        size_t len;
    };
    std::vector<Pkt> order;
    order.reserve(n + n / 50 + 8);
    Rng rng(seed);
    PacketStream ps;
    ps.name = name;
    for (size_t i = 0; i < n; i++) {
        Pkt p{static_cast<uint32_t>(i + 1), static_cast<uint64_t>(i) * payload,
              static_cast<size_t>(std::min<uint64_t>(payload, total - static_cast<uint64_t>(i) * payload))};
        // keep first and last packet so every rep starts and ends cleanly
        bool edge = i == 0 || i + 1 == n;
        if (!edge && rng.uniform() < p_drop) {
            ps.dropped++;
            continue;
        }
        order.push_back(p);
        if (!edge && rng.uniform() < p_dup) {
            order.push_back(p);
            ps.duplicated++;
        }
    }
    for (size_t i = 1; i + 2 < order.size(); i++) {
        if (rng.uniform() < p_swap) {
            std::swap(order[i], order[i + 1]);
            ps.swapped++;
            i++;
        }
    }
    {
        // the tail continues the stream exactly where frame `frames` begins
        uint32_t seq = static_cast<uint32_t>(n + 1);
        uint64_t off = total;
        for (size_t i = 0; i < tail_packets; i++, seq++, off += payload) order.push_back(Pkt{seq, off, payload});
    }

    // materialise: header (seq LE32, byte count LE48) + payload. Payload bytes
    // are a deterministic function of stream offset, so a duplicate carries the
    // same data as its original.
    size_t bytes = 0;
    for (const Pkt& p : order) bytes += kHeader + p.len;
    ps.buf.resize(bytes);
    size_t at = 0;
    for (const Pkt& p : order) {
        uint8_t* d = &ps.buf[at];
        for (int i = 0; i < 4; i++) d[i] = static_cast<uint8_t>(p.seq >> (8 * i));
        for (int i = 0; i < 6; i++) d[4 + i] = static_cast<uint8_t>(p.offset >> (8 * i));
        Rng data(0x9E3779B97F4A7C15ULL ^ p.offset);
        for (size_t k = 0; k < p.len; k += 8) {
            uint64_t v = data.next();
            std::memcpy(d + kHeader + k, &v, std::min<size_t>(8, p.len - k));
        }
        ps.off.push_back(at);
        ps.len.push_back(kHeader + p.len);
        ps.payload_bytes += p.len;
        at += kHeader + p.len;
    }
    return ps;
}

struct Sample {
    double frames_per_s, ns_per_byte, allocs_per_frame;
    uint64_t frames;
};

struct Stats {
    Sample median, best;
};

Stats summarize(std::vector<Sample> v) {
    Stats s;
    std::sort(v.begin(), v.end(), [](const Sample& a, const Sample& b) { return a.ns_per_byte < b.ns_per_byte; });
    s.best = v.front();
    s.median = v[v.size() / 2];
    return s;
}

Sample converter_only(Kernel& k, const std::vector<uint8_t>& frame, size_t frames) {
    uint64_t a0 = g_allocs;
    Clock::time_point t0 = Clock::now();
    for (size_t i = 0; i < frames; i++) {
        k.convert(frame);
        escape(k.data_ptr());
    }
    double ns = std::chrono::duration<double, std::nano>(Clock::now() - t0).count();
    uint64_t allocs = g_allocs - a0;
    return {frames / (ns * 1e-9), ns / (static_cast<double>(frame.size()) * frames),
            static_cast<double>(allocs) / frames, frames};
}

struct ReplayResult {
    Sample s;
    FrameAssembler::Stats st;
};

ReplayResult replay(Kernel& k, const PacketStream& ps, size_t bytes_per_frame) {
    FrameAssembler fa;
    // untimed: allocates the frame buffers. Same reorder slack as DCA1000Handler.
    fa.configure(bytes_per_frame, FrameAssembler::kDefaultReorderSlackPackets * (kPacketBytes - kHeader));
    uint64_t frames = 0;
    uint64_t a0 = g_allocs;
    Clock::time_point t0 = Clock::now();
    const uint8_t* base = ps.buf.data();
    for (size_t i = 0; i < ps.off.size(); i++) {
        int done = fa.push_packet(base + ps.off[i], static_cast<int>(ps.len[i]));
        for (int f = 0; f < done; f++) {  // as DCA1000Handler::process_next_packet
            k.convert(fa.get_frame_bytes());
            escape(k.data_ptr());
            frames++;
        }
    }
    // end of stream: a last frame with a dropped packet is still open
    for (int f = 0, done = fa.flush(); f < done; f++) {
        k.convert(fa.get_frame_bytes());
        escape(k.data_ptr());
        frames++;
    }
    double ns = std::chrono::duration<double, std::nano>(Clock::now() - t0).count();
    uint64_t allocs = g_allocs - a0;
    ReplayResult r;
    r.s = {frames / (ns * 1e-9), ns / static_cast<double>(ps.payload_bytes),
           frames ? static_cast<double>(allocs) / frames : 0.0, frames};
    r.st = fa.get_stats();
    return r;
}

// ---------------------------------------------------------------------------
// Driver replay: DCA1000Handler over a packet stream, as the DCA worker runs it
// ---------------------------------------------------------------------------
struct DriverRig {
    SystemConfigReader sys;
    RadarConfigReader radar;
    std::string out_dir;
};

// a schema v2 IWR1843 + DCA1000 system config for `cfg` (no port is opened:
// the bench calls configure_pipeline() only), adc_data.bin in `out_dir`
bool make_driver_rig(DriverRig& rig, const std::string& cfg, const std::string& out_dir, bool save,
                     const std::string& json_path) {
    setenv(SystemConfigReader::kBoardsDirEnv, (std::string(CONFIG_DIR) + "/boards").c_str(), 0);
    {
        std::ofstream j(json_path);
        j << "{\n"
             "  \"schema_version\": 2,\n"
             "  \"board\": \"IWR1843\",\n"
             "  \"firmware\": \"demo\",\n"
             "  \"runtime\": { \"firmware_check\": \"off\" },\n"
             "  \"radar_cfg\": \"" << cfg << "\",\n"
             "  \"cli\": { \"port\": \"/dev/null-not-opened\" },\n"
             "  \"dca1000\": { \"enabled\": true, \"fpga_ip\": \"127.0.0.1\", \"host_ip\": \"127.0.0.1\",\n"
             "               \"cmd_port\": 4096, \"data_port\": 4098 },\n"
             "  \"output\": { \"dir\": \"" << out_dir << "\", \"save_adc_frames\": " << (save ? "true" : "false")
          << ", \"save_raw_lvds\": false }\n"
             "}\n";
        if (!j) return false;
    }
    if (!rig.sys.initialize(json_path)) return false;
    const cpsl::radar::BoardDescriptor& b = rig.sys.getBoard();
    rig.radar.initialize(rig.sys.getRadarConfigPath(), b.cfg_dialect.rx_mask_fields, b.cfg_dialect.frame_period_field);
    rig.out_dir = out_dir;
    return rig.radar.initialized;
}

struct DriverResult {
    Sample s;
    FrameAssembler::Stats st;
    uint64_t log_messages = 0;
};

std::atomic<uint64_t> g_log_messages{0};

DriverResult replay_driver(const DriverRig& rig, const PacketStream& ps) {
    DriverResult r;
    {
        DCA1000Handler h;
        // untimed: opens adc_data.bin (when saving) and sizes the frame buffers
        if (!h.configure_pipeline(rig.sys, rig.radar)) {
            std::fprintf(stderr, "FAIL: DCA1000Handler::configure_pipeline\n");
            std::exit(1);
        }
        const uint64_t m0 = g_log_messages;
        uint64_t a0 = g_allocs;
        Clock::time_point t0 = Clock::now();
        const uint8_t* base = ps.buf.data();
        for (size_t i = 0; i < ps.off.size(); i++) {
            h.ingest_packet(base + ps.off[i], static_cast<int>(ps.len[i]));
        }
        double ns = std::chrono::duration<double, std::nano>(Clock::now() - t0).count();
        uint64_t allocs = g_allocs - a0;
        r.log_messages = g_log_messages - m0;
        h.stop();  // untimed: flush and close adc_data.bin
        const DCA1000Handler::Stats st = h.get_stats();
        r.s = {st.frames / (ns * 1e-9), ns / static_cast<double>(ps.payload_bytes),
               st.frames ? static_cast<double>(allocs) / st.frames : 0.0, st.frames};
        r.st = st.assembler;
    }
    std::error_code ec;
    std::filesystem::remove(rig.out_dir + "/adc_data.bin", ec);
    return r;
}

std::string cpu_model() {
    std::ifstream f("/proc/cpuinfo");
    std::string line;
    while (std::getline(f, line)) {
        if (line.compare(0, 10, "model name") == 0) {
            std::string::size_type c = line.find(':');
            if (c != std::string::npos) return line.substr(c + 2);
        }
    }
    return "unknown";
}

// one row per variant; "x (a)" = median ns/byte of (a) / median ns/byte of this variant
void print_rows(const char* scenario, std::unique_ptr<Kernel> (&k)[3], std::vector<Sample> (&runs)[3]) {
    Stats s[3];
    for (int v = 0; v < 3; v++) s[v] = summarize(runs[v]);
    for (int v = 0; v < 3; v++) {
        std::printf("  %-12s (%s) %-26s %10.1f [%10.1f] %8.3f [%8.3f] %12.1f %7.2fx\n", scenario, k[v]->id(),
                    k[v]->label(), s[v].median.frames_per_s, s[v].best.frames_per_s, s[v].median.ns_per_byte,
                    s[v].best.ns_per_byte, s[v].median.allocs_per_frame,
                    s[0].median.ns_per_byte / s[v].median.ns_per_byte);
    }
}

void print_driver_row(const char* scenario, const std::vector<Sample>& runs) {
    Stats s = summarize(runs);
    std::printf("  %-12s (d) %-26s %10.1f [%10.1f] %8.3f [%8.3f] %12.1f %8s\n", scenario, "DCA1000Handler (driver)",
                s.median.frames_per_s, s.best.frames_per_s, s.median.ns_per_byte, s.best.ns_per_byte,
                s.median.allocs_per_frame, "-");
}

// ---------------------------------------------------------------------------
// --udp: loopback replay through the real DCA1000Socket and the DCA worker path
// ---------------------------------------------------------------------------

// The DCA1000Socket half of UdpPacketSource, without the FPGA command
// protocol (nothing answers on loopback): open() binds the sockets,
// start()/stop() run the RX thread, acquire()/release() (and pop()) read the
// packet ring as UdpPacketSource does.
class LoopbackSource : public cpsl::radar::PacketSource {
public:
    LoopbackSource(int cmd_port, int data_port, size_t rcvbuf, cpsl::radar::ThreadPlacement rx)
        : cmd_port_(cmd_port), data_port_(data_port), rcvbuf_(rcvbuf), rx_(rx) {}
    cpsl::radar::Status open() override {
        if (!socket_.init("127.0.0.1", "127.0.0.1", cmd_port_, data_port_, rcvbuf_))
            return cpsl::radar::Status(cpsl::radar::Code::open_failed, "cannot bind the loopback sockets");
        return cpsl::radar::Status::ok();
    }
    cpsl::radar::Status configure() override { return cpsl::radar::Status::ok(); }
    cpsl::radar::Status start() override {
        socket_.start_rx(rx_);
        return cpsl::radar::Status::ok();
    }
    cpsl::radar::Status stop() override {
        socket_.stop_rx();
        return cpsl::radar::Status::ok();
    }
    bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) override {
        if (!socket_.pop_packet(buf, len, static_cast<int>(timeout.count()))) return false;
        delivered_.fetch_add(1, std::memory_order_relaxed);
        return true;
    }
    size_t acquire(PacketView* out, size_t max, std::chrono::milliseconds timeout) override {
        const int n = socket_.acquire_packets(out, static_cast<int>(max), static_cast<int>(timeout.count()));
        delivered_.fetch_add(static_cast<uint64_t>(n), std::memory_order_relaxed);
        return static_cast<size_t>(n);
    }
    void release(size_t n) override { socket_.release_packets(static_cast<int>(n)); }
    uint32_t overrun_count() const override { return socket_.get_overrun_count(); }
    uint32_t ring_full_count() const override { return socket_.get_ring_full_count(); }
    uint32_t kernel_drops() const override { return socket_.get_kernel_drops(); }
    size_t rcvbuf_bytes() const override { return socket_.get_granted_rcvbuf(); }
    uint64_t delivered() const { return delivered_.load(std::memory_order_relaxed); }

private:
    int cmd_port_, data_port_;
    size_t rcvbuf_;
    cpsl::radar::ThreadPlacement rx_;
    DCA1000Socket socket_;
    std::atomic<uint64_t> delivered_{0};
};

// a free UDP port on 127.0.0.1 (bound to port 0, read back, closed)
int free_udp_port() {
    const int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = 0;
    socklen_t n = sizeof(a);
    int port = -1;
    if (bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0 &&
        getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n) == 0)
        port = ntohs(a.sin_port);
    close(fd);
    return port;
}

// the drops column of 127.0.0.1:<port> in /proc/net/udp (-1: not found)
long long kernel_drops(int port) {
    std::ifstream f("/proc/net/udp");
    std::string line;
    char want[32];
    std::snprintf(want, sizeof want, "0100007F:%04X", port);
    std::getline(f, line);  // header
    while (std::getline(f, line)) {
        if (line.find(want) == std::string::npos) continue;
        // sl local rem st tx:rx tr:tm retrnsmt uid timeout inode ref pointer drops
        std::vector<std::string> tok;
        size_t i = 0;
        while (i < line.size()) {
            while (i < line.size() && line[i] == ' ') i++;
            size_t j = i;
            while (j < line.size() && line[j] != ' ') j++;
            if (j > i) tok.push_back(line.substr(i, j - i));
            i = j;
        }
        if (tok.size() >= 13 && tok[1] == want) return std::strtoll(tok.back().c_str(), nullptr, 10);
    }
    return -1;
}

double cpu_ns(const rusage& r) {
    return (r.ru_utime.tv_sec + r.ru_stime.tv_sec) * 1e9 + (r.ru_utime.tv_usec + r.ru_stime.tv_usec) * 1e3;
}

struct ThreadUsage {
    double ns = 0;
    long vcsw = 0, ivcsw = 0;
};

ThreadUsage usage_delta(const rusage& a, const rusage& b) {
    return {cpu_ns(b) - cpu_ns(a), b.ru_nvcsw - a.ru_nvcsw, b.ru_nivcsw - a.ru_nivcsw};
}

struct UdpOptions {
    double rate = 3460;  // packets/s, 0 = max; 3460 = the core-04 IWR1843 baseline
    uint32_t stall_ms = 0;
    uint32_t stall_every = 0;
    size_t rcvbuf = 64 * 1024 * 1024;  // dca1000.rcvbuf_bytes default
    // runtime.rx_cpu / worker_cpu (-1: not pinned) and the RX thread's
    // SCHED_RR priority as the driver asks for it (99; a warning without cap_sys_nice)
    int rx_cpu = -1, worker_cpu = -1;
};

int run_udp(const std::string& cfg, size_t frames, size_t bytes_per_frame, const UdpOptions& o,
            const std::string& tmp_base) {
    const int cmd_port = free_udp_port(), data_port = free_udp_port();
    if (cmd_port <= 0 || data_port <= 0 || cmd_port == data_port) {
        std::fprintf(stderr, "cannot find two free UDP ports on 127.0.0.1\n");
        return 1;
    }
    std::string tmp_dir = tmp_base + "/bench_pipeline_XXXXXX";
    if (mkdtemp(&tmp_dir[0]) == nullptr) {
        std::fprintf(stderr, "cannot create a temp dir under %s\n", tmp_base.c_str());
        return 1;
    }
    DriverRig rig;
    if (!make_driver_rig(rig, cfg, tmp_dir, false, tmp_dir + "/udp.json") ||
        rig.radar.get_bytes_per_frame() != bytes_per_frame) {
        std::fprintf(stderr, "cannot build the driver rig for %s\n", cfg.c_str());
        return 1;
    }
    const size_t tail = FrameAssembler::kDefaultReorderSlackPackets + 1;
    const PacketStream ps = make_stream("udp", bytes_per_frame, frames, 0, 0, 0, 1, tail);
    const uint64_t frame_payload = static_cast<uint64_t>(bytes_per_frame) * frames;

    auto src = std::make_shared<LoopbackSource>(cmd_port, data_port, o.rcvbuf,
                                                cpsl::radar::ThreadPlacement{o.rx_cpu, 99});
    if (!src->open()) {
        std::fprintf(stderr, "cannot bind 127.0.0.1:%d/%d\n", cmd_port, data_port);
        return 1;
    }
    DCA1000Handler h;
    if (!h.configure_pipeline(rig.sys, rig.radar)) {
        std::fprintf(stderr, "FAIL: DCA1000Handler::configure_pipeline\n");
        return 1;
    }
    h.set_packet_source(src);
    // consumer stall: the worker sleeps in the publish hook
    std::atomic<uint64_t> stalls{0};
    uint64_t published = 0;
    if (o.stall_ms > 0) {
        const uint64_t every = o.stall_every, once = std::max<uint64_t>(1, frames / 2);
        h.set_publish_hook([&, every, once] {
            published++;
            if (every ? published % every == 0 : published == once) {
                std::this_thread::sleep_for(std::chrono::milliseconds(o.stall_ms));
                stalls.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }

    rusage self0{}, main0{};
    getrusage(RUSAGE_SELF, &self0);
    getrusage(RUSAGE_THREAD, &main0);
    src->start();
    std::atomic<bool> stop{false};
    std::thread worker([&] {
        cpsl::radar::apply_thread_placement(pthread_self(), {o.worker_cpu, 0}, "bench worker");
        while (!stop.load(std::memory_order_relaxed)) h.process_next_packet();
    });

    // sender: the stream at o.rate packets/s (0 = as fast as send() goes)
    ThreadUsage sender_use;
    uint64_t sent = 0, send_errors = 0;
    double send_s = 0;
    std::thread sender([&] {
        rusage r0{}, r1{};
        getrusage(RUSAGE_THREAD, &r0);
        const int fd = socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in to{};
        to.sin_family = AF_INET;
        to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        to.sin_port = htons(static_cast<uint16_t>(data_port));
        connect(fd, reinterpret_cast<sockaddr*>(&to), sizeof(to));
        const Clock::time_point t0 = Clock::now();
        const uint8_t* base = ps.buf.data();
        for (size_t i = 0; i < ps.off.size(); i++) {
            if (o.rate > 0) {
                // pace by schedule: catch up in bursts, sleep when ahead
                const Clock::time_point due = t0 + std::chrono::nanoseconds(static_cast<int64_t>(i * 1e9 / o.rate));
                const Clock::time_point now = Clock::now();
                if (due > now + std::chrono::microseconds(50)) std::this_thread::sleep_until(due);
            }
            if (send(fd, base + ps.off[i], ps.len[i], 0) == static_cast<ssize_t>(ps.len[i])) sent++;
            else send_errors++;
        }
        send_s = std::chrono::duration<double>(Clock::now() - t0).count();
        close(fd);
        getrusage(RUSAGE_THREAD, &r1);
        sender_use = usage_delta(r0, r1);
    });
    sender.join();

    // wait until every frame is in, or nothing has moved for 1 s
    uint64_t last = ~uint64_t(0);
    Clock::time_point moved = Clock::now();
    for (;;) {
        const uint64_t d = src->delivered();
        if (h.get_stats().frames >= frames && d >= sent) break;
        if (d != last) {
            last = d;
            moved = Clock::now();
        } else if (Clock::now() - moved > std::chrono::seconds(1)) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    stop.store(true);
    worker.join();
    const long long kdrops = kernel_drops(data_port);  // before the socket closes
    h.stop();                                          // joins the RX thread
    const uint32_t driver_kdrops = src->kernel_drops(), ring_full = src->ring_full_count();
    rusage self1{}, main1{};
    getrusage(RUSAGE_THREAD, &main1);
    getrusage(RUSAGE_SELF, &self1);

    const ThreadUsage all = usage_delta(self0, self1), main_use = usage_delta(main0, main1);
    const double ns = all.ns - sender_use.ns - main_use.ns;
    const long vcsw = all.vcsw - sender_use.vcsw - main_use.vcsw;
    const long ivcsw = all.ivcsw - sender_use.ivcsw - main_use.ivcsw;
    const DCA1000Handler::Stats st = h.get_stats();
    const uint64_t delivered = src->delivered();
    const uint64_t discards = src->overrun_count();
    const uint64_t kd = kdrops > 0 ? static_cast<uint64_t>(kdrops) : 0;
    const long long unaccounted = static_cast<long long>(sent) - static_cast<long long>(delivered) -
                                  static_cast<long long>(discards) - static_cast<long long>(kd);
    const bool golden = st.frames == frames && st.assembler.incomplete_frames == 0 &&
                        st.assembler.skipped_frames == 0 && st.assembler.dropped_packets == 0;
    char rate[32];
    if (o.rate > 0) std::snprintf(rate, sizeof rate, "%.0f", o.rate);
    else std::snprintf(rate, sizeof rate, "max");

    std::printf("  udp loopback: 127.0.0.1 data port %d, SO_RCVBUF requested %zu granted %zu, rate %s packets/s "
                "(achieved %.0f), stall %u ms %s, rx_cpu %d, worker_cpu %d\n",
                data_port, o.rcvbuf, src->rcvbuf_bytes(), rate, sent / std::max(send_s, 1e-9), o.stall_ms,
                o.stall_ms == 0 ? "(none)"
                : o.stall_every ? ("every " + std::to_string(o.stall_every) + " frames").c_str()
                                : "once, mid-run",
                o.rx_cpu, o.worker_cpu);
    std::printf("udp frames=%llu of=%zu golden=%s sent=%llu delivered=%llu discards=%llu kernel_drops=%lld "
                "unaccounted=%lld stalls=%llu cpu_ns_per_byte=%.3f cpu_ms=%.1f vol_cs=%ld invol_cs=%ld "
                "cs_per_packet=%.3f dropped=%u incomplete=%u skipped=%u late=%u rate=%s driver_kernel_drops=%u "
                "ring_full=%u\n",
                static_cast<unsigned long long>(st.frames), frames, golden ? "yes" : "no",
                static_cast<unsigned long long>(sent), static_cast<unsigned long long>(delivered),
                static_cast<unsigned long long>(discards), kdrops, unaccounted,
                static_cast<unsigned long long>(stalls.load()), ns / static_cast<double>(frame_payload), ns * 1e-6,
                vcsw, ivcsw, sent ? static_cast<double>(vcsw + ivcsw) / static_cast<double>(sent) : 0.0,
                st.assembler.dropped_packets, st.assembler.incomplete_frames, st.assembler.skipped_frames,
                st.assembler.late_packets, rate, driver_kdrops, ring_full);
    std::printf("\n  cpu_ns_per_byte / vol_cs / invol_cs: the RX and worker threads only (process getrusage minus\n"
                "  the sender and main threads), per frame payload byte. discards: packets the RX thread threw\n"
                "  away (DCA1000Socket overrun count). kernel_drops: the socket's drops column in /proc/net/udp;\n"
                "  driver_kernel_drops: the same count as the driver reports it (Stats::kernel_drops, P6).\n"
                "  ring_full: times the RX thread found its ring full and stopped reading.\n"
                "  unaccounted = sent - delivered - discards - kernel_drops (0 when every loss is counted).\n"
                "  golden: every frame complete, nothing dropped.\n");
    std::error_code ec;
    std::filesystem::remove_all(tmp_dir, ec);
    if (send_errors > 0) std::fprintf(stderr, "note: %llu send() errors\n", static_cast<unsigned long long>(send_errors));
    // a run that lost data is fine only if every lost packet was counted
    if (!golden && unaccounted != 0) {
        std::fprintf(stderr, "FAIL: frames not golden and %lld packets unaccounted\n", unaccounted);
        return 1;
    }
    if (!golden && discards == 0 && kd == 0) {
        std::fprintf(stderr, "FAIL: frames not golden with no counted loss\n");
        return 1;
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::string cfg = std::string(CONFIG_DIR) + "/radar/nav_configs/1843_stress_test.cfg";
    size_t frames = 40;
    size_t reps = 7;
    std::string log_level = "info";
    bool udp = false;
    UdpOptions udp_opt;
    std::string tmp_base = std::filesystem::is_directory("/dev/shm") && access("/dev/shm", W_OK) == 0 ? "/dev/shm"
                                                                                                       : "/tmp";
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--cfg" && i + 1 < argc) cfg = argv[++i];
        else if (a == "--frames" && i + 1 < argc) frames = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--reps" && i + 1 < argc) reps = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--log-level" && i + 1 < argc) log_level = argv[++i];
        else if (a == "--tmp-dir" && i + 1 < argc) tmp_base = argv[++i];
        else if (a == "--udp") udp = true;
        else if (a == "--udp-rate" && i + 1 < argc) {
            const std::string v = argv[++i];
            udp_opt.rate = v == "max" ? 0 : std::strtod(v.c_str(), nullptr);
            if (v != "max" && !(udp_opt.rate > 0)) {
                std::fprintf(stderr, "--udp-rate must be packets/s > 0 or max\n");
                return 2;
            }
        } else if (a == "--stall-ms" && i + 1 < argc) udp_opt.stall_ms = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--stall-every" && i + 1 < argc) udp_opt.stall_every = std::strtoul(argv[++i], nullptr, 10);
        else if (a == "--udp-rcvbuf" && i + 1 < argc) udp_opt.rcvbuf = std::strtoull(argv[++i], nullptr, 10);
        else if (a == "--rx-cpu" && i + 1 < argc) udp_opt.rx_cpu = std::atoi(argv[++i]);
        else if (a == "--worker-cpu" && i + 1 < argc) udp_opt.worker_cpu = std::atoi(argv[++i]);
        else {
            std::fprintf(stderr,
                         "usage: %s [--cfg <radar .cfg>] [--frames N] [--reps N] [--log-level error|warn|info|debug]"
                         " [--tmp-dir DIR]\n"
                         "       %s --udp [--cfg <radar .cfg>] [--frames N] [--udp-rate PKT_PER_S|max]"
                         " [--stall-ms N [--stall-every K]] [--udp-rcvbuf BYTES] [--rx-cpu N] [--worker-cpu N]\n",
                         argv[0], argv[0]);
            return 2;
        }
    }
    cpsl::radar::LogLevel level;
    if (log_level == "error") level = cpsl::radar::LogLevel::error;
    else if (log_level == "warn") level = cpsl::radar::LogLevel::warn;
    else if (log_level == "info") level = cpsl::radar::LogLevel::info;
    else if (log_level == "debug") level = cpsl::radar::LogLevel::debug;
    else {
        std::fprintf(stderr, "--log-level must be error, warn, info or debug\n");
        return 2;
    }
    if (frames < 2 || reps < 1) {
        std::fprintf(stderr, "need --frames >= 2 and --reps >= 1\n");
        return 2;
    }

    // frame shape from a real radar cfg, through today's RadarConfigReader
    FrameShape shape;
    {
        std::streambuf* old = std::cout.rdbuf();
        NullBuf quiet;
        std::cout.rdbuf(&quiet);
        RadarConfigReader rc(cfg);
        std::cout.rdbuf(old);
        if (!rc.initialized) {
            std::fprintf(stderr, "cannot read radar cfg %s\n", cfg.c_str());
            return 1;
        }
        shape.rx = rc.get_num_rx_antennas();
        shape.samples = rc.get_samples_per_chirp();
        shape.chirps = rc.get_chirps_per_frame();
        if (rc.get_bytes_per_frame() != shape.bytes()) {
            std::fprintf(stderr, "bytes_per_frame mismatch\n");
            return 1;
        }
    }
    if (shape.samples % 2 != 0) {
        std::fprintf(stderr, "bench kernels need an even sample count (got %zu)\n", shape.samples);
        return 1;
    }
    const size_t B = shape.bytes();

    struct utsname un;
    uname(&un);
#if defined(__clang__)
    const char* cc = "clang";
#elif defined(__GNUC__)
    const char* cc = "gcc";
#else
    const char* cc = "";
#endif
#ifdef __OPTIMIZE__
    const char* opt = "yes";
#else
    const char* opt = "NO (numbers are not comparable with optimized builds)";
#endif
    std::printf("bench_pipeline (core-09)\n");
    const char* build_type = std::strlen(BENCH_BUILD_TYPE) ? BENCH_BUILD_TYPE : "(none)";
    std::printf("  build type : %s   optimized: %s   compiler: %s %s\n", build_type, opt, cc, __VERSION__);
    std::printf("  host       : %s, %s, %s %s\n", un.nodename, cpu_model().c_str(), un.sysname, un.release);
    std::printf("  frame      : %zu rx x %zu samples x %zu chirps = %zu B (%zu packets of %zu B), from %s\n",
                shape.rx, shape.samples, shape.chirps, B, (B + kPacketBytes - kHeader - 1) / (kPacketBytes - kHeader),
                kPacketBytes, cfg.c_str());
    std::printf("  layout     : two_lane_iq_pairs, q_first (IWR1843/IWR6843 path)\n");
    if (udp) {
        std::printf("  mode       : --udp loopback (sender thread -> 127.0.0.1 -> DCA1000Socket RX thread -> DCA worker)\n");
        cpsl::radar::set_log_level(level);
        cpsl::radar::set_log_sink([](cpsl::radar::LogLevel, const std::string&) { ++g_log_messages; });
        const int rc = run_udp(cfg, frames, B, udp_opt, tmp_base);
        cpsl::radar::set_log_sink(nullptr);
        return rc;
    }

    std::printf("  method     : %zu frames per rep, 1 warm-up + %zu timed reps, variants interleaved per rep;\n"
                "               median rep shown, best rep in [brackets]; single thread\n",
                frames, reps);
    std::printf("  driver rows: log level %s (counting sink), adc_data.bin for drv_save in %s\n", log_level.c_str(),
                tmp_base.c_str());

    std::unique_ptr<Kernel> kernels[3] = {std::unique_ptr<Kernel>(new bench::TodayKernel()),
                                          std::unique_ptr<Kernel>(new bench::NestedReusedKernel()),
                                          std::unique_ptr<Kernel>(new bench::FlatKernel())};
    for (auto& k : kernels) k->configure(shape);

    // ---- equivalence: all variants decode the same frame identically ----
    PacketStream clean = make_stream("clean", B, frames, 0, 0, 0, 1);
    std::vector<uint8_t> frame(clean.buf.size() > 0 ? B : 0);
    {
        // first frame's payload, taken straight from the clean stream
        size_t at = 0;
        for (size_t i = 0; i < clean.off.size() && at < B; i++) {
            size_t n = std::min(clean.len[i] - kHeader, B - at);
            std::memcpy(&frame[at], &clean.buf[clean.off[i] + kHeader], n);
            at += n;
        }
    }
    for (auto& k : kernels) k->convert(frame);
    size_t mismatches = 0;
    for (size_t r = 0; r < shape.rx; r++)
        for (size_t s = 0; s < shape.samples; s++)
            for (size_t c = 0; c < shape.chirps; c++) {
                bench::Sample ref = kernels[0]->at(r, s, c);
                if (!(kernels[1]->at(r, s, c) == ref) || !(kernels[2]->at(r, s, c) == ref)) mismatches++;
            }
    std::printf("  equivalence: (b) and (c) match (a) on all %zu samples of a random frame: %s\n\n",
                shape.rx * shape.samples * shape.chirps, mismatches == 0 ? "yes" : "NO");
    if (mismatches != 0) {
        std::fprintf(stderr, "FAIL: %zu mismatching samples\n", mismatches);
        return 1;
    }

    std::printf("  %-12s %-30s %23s %19s %12s %8s\n", "", "variant", "frames/s [best]", "ns/byte [best]",
                "allocs/frame", "x (a)");

    // ---- 1. converter only ----
    {
        std::vector<Sample> runs[3];
        for (size_t rep = 0; rep <= reps; rep++) {
            for (int v = 0; v < 3; v++) {
                Sample s = converter_only(*kernels[v], frame, frames);
                if (rep > 0) runs[v].push_back(s);  // rep 0 is the warm-up
            }
        }
        print_rows("converter", kernels, runs);
    }

    // ---- 2. pipeline replay ----
    PacketStream streams[3] = {std::move(clean), make_stream("drop_1pct", B, frames, 0.01, 0, 0, 2),
                               make_stream("dup_reorder", B, frames, 0, 0.005, 0.005, 3)};
    std::vector<std::string> notes;
    bool golden_ok = true;
    std::streambuf* old = std::cout.rdbuf();
    NullBuf quiet;
    for (const PacketStream& ps : streams) {
        std::vector<Sample> runs[3];
        FrameAssembler::Stats st{};
        std::cout.rdbuf(&quiet);
        for (size_t rep = 0; rep <= reps; rep++) {
            for (int v = 0; v < 3; v++) {
                ReplayResult r = replay(*kernels[v], ps, B);
                if (rep > 0) runs[v].push_back(r.s);
                st = r.st;
            }
        }
        std::cout.rdbuf(old);
        print_rows(ps.name.c_str(), kernels, runs);
        char buf[640];
        const unsigned long long done = static_cast<unsigned long long>(runs[0].front().frames);
        std::snprintf(buf, sizeof buf,
                      "%-12s %zu packets (%zu dropped, %zu duplicated, %zu swapped); frames completed %llu of %zu "
                      "(%s); assembler stats: dropped_packets %u, drop events (gaps not filled) %u, late %u, duplicate %u, "
                      "incomplete frames %u, skipped frames %u",
                      ps.name.c_str(), ps.off.size(), ps.dropped, ps.duplicated, ps.swapped, done, frames,
                      done == frames ? "= golden" : "NOT golden", st.dropped_packets, st.dropped_packet_events,
                      st.late_packets, st.duplicate_packets, st.incomplete_frames, st.skipped_frames);
        notes.push_back(buf);
        if (done != frames) golden_ok = false;
    }

    // ---- 3. driver replay (DCA1000Handler) ----
    std::string tmp_dir = tmp_base + "/bench_pipeline_XXXXXX";
    if (mkdtemp(&tmp_dir[0]) == nullptr) {
        std::fprintf(stderr, "cannot create a temp dir under %s\n", tmp_base.c_str());
        return 1;
    }
    DriverRig rig_nosave, rig_save;
    if (!make_driver_rig(rig_nosave, cfg, tmp_dir, false, tmp_dir + "/nosave.json") ||
        !make_driver_rig(rig_save, cfg, tmp_dir, true, tmp_dir + "/save.json") ||
        rig_save.radar.get_bytes_per_frame() != B) {
        std::fprintf(stderr, "cannot build the driver rig for %s\n", cfg.c_str());
        return 1;
    }
    cpsl::radar::set_log_level(level);
    cpsl::radar::set_log_sink([](cpsl::radar::LogLevel, const std::string&) { ++g_log_messages; });
    {
        const size_t tail = FrameAssembler::kDefaultReorderSlackPackets + 1;
        struct DriverScenario {
            const char* name;
            PacketStream ps;
            const DriverRig* rig;
        };
        DriverScenario ds[3] = {
            {"drv_clean", make_stream("drv_clean", B, frames, 0, 0, 0, 1, tail), &rig_nosave},
            {"drv_drop_1pct", make_stream("drv_drop_1pct", B, frames, 0.01, 0, 0, 2, tail), &rig_nosave},
            {"drv_save", make_stream("drv_save", B, frames, 0, 0, 0, 1, tail), &rig_save},
        };
        std::cout.rdbuf(&quiet);
        std::vector<Sample> runs[3];
        DriverResult last[3];
        for (size_t rep = 0; rep <= reps; rep++) {
            for (int v = 0; v < 3; v++) {
                DriverResult r = replay_driver(*ds[v].rig, ds[v].ps);
                if (rep > 0) runs[v].push_back(r.s);
                last[v] = r;
            }
        }
        std::cout.rdbuf(old);
        for (int v = 0; v < 3; v++) {
            print_driver_row(ds[v].name, runs[v]);
            const PacketStream& ps = ds[v].ps;
            const FrameAssembler::Stats& st = last[v].st;
            char buf[640];
            const unsigned long long done = static_cast<unsigned long long>(runs[v].front().frames);
            std::snprintf(buf, sizeof buf,
                          "%-12s %zu packets (%zu dropped, %zu duplicated, %zu swapped, %zu tail); frames completed "
                          "%llu of %zu (%s); assembler stats: dropped_packets %u, drop events (gaps not filled) %u, late %u, "
                          "duplicate %u, incomplete frames %u, skipped frames %u; log messages per rep %llu",
                          ps.name.c_str(), ps.off.size(), ps.dropped, ps.duplicated, ps.swapped, tail, done, frames,
                          done == frames ? "= golden" : "NOT golden", st.dropped_packets, st.dropped_packet_events,
                          st.late_packets, st.duplicate_packets, st.incomplete_frames, st.skipped_frames,
                          static_cast<unsigned long long>(last[v].log_messages));
            notes.push_back(buf);
            for (const Sample& r : runs[v])
                if (r.frames != frames) golden_ok = false;
        }
    }
    cpsl::radar::set_log_sink(nullptr);
    std::error_code ec;
    std::filesystem::remove_all(tmp_dir, ec);

    std::printf("\n  replay input:\n");
    for (const std::string& n : notes) std::printf("    %s\n", n.c_str());
    std::printf("\n  ns/byte: wall-clock time per ADC payload byte on one thread. allocs/frame: operator new\n"
                "  calls in the timed region / frames converted. x (a): how many times faster than (a), by\n"
                "  median ns/byte. Replay rows include the driver's FrameAssembler (byte-offset placement,\n"
                "  core-11 P1; flushed at end of stream), identical for every variant. drv_* rows (d) run the\n"
                "  driver's DCA1000Handler instead (no flush: a clean tail closes the last frame). Every replay\n"
                "  row must complete exactly the requested number of frames (\"= golden\"). Compare variants\n"
                "  within a row group, not across groups.\n");
    if (!golden_ok) {
        std::fprintf(stderr, "FAIL: a replay row did not complete the golden frame count\n");
        return 1;
    }
    return 0;
}
