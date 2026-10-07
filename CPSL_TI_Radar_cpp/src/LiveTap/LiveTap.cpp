#include "LiveTap.hpp"

#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "Log.hpp"

namespace cpsl {
namespace radar {
namespace livetap {

namespace {

std::vector<uint8_t> frame_message(uint8_t type, const std::string& head, const uint8_t* tail = nullptr,
                                   size_t tail_len = 0) {
    const uint32_t len = static_cast<uint32_t>(1 + head.size() + tail_len);
    std::vector<uint8_t> m;
    m.reserve(4 + len);
    for (int i = 0; i < 4; i++) m.push_back(static_cast<uint8_t>((len >> (8 * i)) & 0xff));
    m.push_back(type);
    m.insert(m.end(), head.begin(), head.end());
    if (tail_len) m.insert(m.end(), tail, tail + tail_len);
    return m;
}

std::string json_string(const std::string& s) {
    std::string o = "\"";
    for (char c : s) {
        if (c == '"' || c == '\\') {
            o += '\\';
            o += c;
        } else if (static_cast<unsigned char>(c) < 0x20) {
            char b[8];
            std::snprintf(b, sizeof b, "\\u%04x", c);
            o += b;
        } else {
            o += c;
        }
    }
    return o + "\"";
}

void append_number(std::string& o, float v) {
    if (!std::isfinite(v)) {
        o += "null";
        return;
    }
    char b[32];
    std::snprintf(b, sizeof b, "%.7g", static_cast<double>(v));
    o += b;
}

}  // namespace

std::vector<uint8_t> encode_hello(const std::string& board, bool points, bool adc, uint32_t adc_every) {
    std::string s = "{\"version\":1,\"board\":" + json_string(board) + ",\"streams\":[";
    if (points) s += "\"points\"";
    if (adc) s += std::string(points ? "," : "") + "\"adc\"";
    s += "],\"adc_every\":" + std::to_string(adc_every) + "}";
    return frame_message(1, s);
}

std::vector<uint8_t> encode_points(const PointCloud& cloud, double unix_time_s) {
    std::string s;
    s.reserve(96 + cloud.points.size() * 56);
    char b[96];
    std::snprintf(b, sizeof b, "{\"type\":\"frame\",\"frame\":%u,\"n\":%zu,\"t\":%.6f,\"pts\":[",
                  static_cast<unsigned>(cloud.frame_number), cloud.points.size(), unix_time_s);
    s += b;
    bool first = true;
    for (const Point& p : cloud.points) {
        s += first ? "[" : ",[";
        first = false;
        const float v[6] = {p.x, p.y, p.z, p.v, p.snr_db, p.noise_db};
        for (int i = 0; i < 6; i++) {
            if (i) s += ',';
            append_number(s, v[i]);
        }
        s += ']';
    }
    s += "]}";
    return frame_message(2, s);
}

std::vector<uint8_t> encode_adc(const AdcFrame& f) {
    const size_t rx = f.data.size();
    const size_t samples = rx ? f.data[0].size() : 0;
    const size_t chirps = samples ? f.data[0][0].size() : 0;
    char b[200];
    std::snprintf(b, sizeof b,
                  "{\"index\":%llu,\"shape\":[%zu,%zu,%zu],\"missing_bytes\":%u,\"layout\":\"rx,sample,chirp\","
                  "\"iq_order\":\"IQ\"}\n",
                  static_cast<unsigned long long>(f.index), rx, samples, chirps,
                  static_cast<unsigned>(f.missing_bytes));
    const std::string head = b;
    const size_t payload = rx * samples * chirps * 4;
    const uint32_t len = static_cast<uint32_t>(1 + head.size() + payload);
    std::vector<uint8_t> m;
    m.reserve(4 + len);
    for (int i = 0; i < 4; i++) m.push_back(static_cast<uint8_t>((len >> (8 * i)) & 0xff));
    m.push_back(3);
    m.insert(m.end(), head.begin(), head.end());
    for (size_t r = 0; r < rx; r++) {
        for (size_t s = 0; s < samples; s++) {
            for (size_t c = 0; c < chirps; c++) {
                const std::complex<int16_t>& z = f.data[r][s][c];
                const uint16_t i16 = static_cast<uint16_t>(z.real()), q16 = static_cast<uint16_t>(z.imag());
                m.push_back(static_cast<uint8_t>(i16 & 0xff));
                m.push_back(static_cast<uint8_t>(i16 >> 8));
                m.push_back(static_cast<uint8_t>(q16 & 0xff));
                m.push_back(static_cast<uint8_t>(q16 >> 8));
            }
        }
    }
    return m;
}

}  // namespace livetap

LiveTap::LiveTap(int fd, uint32_t adc_every) : fd_(fd), adc_every_(adc_every) {}

LiveTap::~LiveTap() {
    stop();
    if (fd_ >= 0) ::close(fd_);
}

void LiveTap::start(const std::string& board, bool points, bool adc) {
    ::signal(SIGPIPE, SIG_IGN);  // a closed reader is an EPIPE from write(), never a dead driver
    const int fl = ::fcntl(fd_, F_GETFL);
    if (fl >= 0) ::fcntl(fd_, F_SETFL, fl | O_NONBLOCK);  // write_all polls so stop() is never stuck
    hello_ = livetap::encode_hello(board, points, adc, adc_every_);
    writer_ = std::thread([this] { run(); });
}

void LiveTap::stop() {
    {
        std::lock_guard<std::mutex> l(m_);
        stopping_ = true;
    }
    stop_flag_ = true;
    cv_.notify_all();
    if (writer_.joinable()) writer_.join();
}

void LiveTap::push_points(const PointCloud& cloud) {
    if (disabled_.load()) return;
    const double t = std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
    std::vector<uint8_t> m = livetap::encode_points(cloud, t);
    {
        std::lock_guard<std::mutex> l(m_);
        if (!points_.empty()) skipped_++;
        points_.swap(m);
    }
    cv_.notify_one();
}

void LiveTap::offer_adc(const AdcFrame& frame) {
    if (adc_every_ == 0 || disabled_.load()) return;
    const bool due = adc_seen_ % adc_every_ == 0;
    adc_seen_++;
    if (!due) return;
    std::vector<uint8_t> m = livetap::encode_adc(frame);
    {
        std::lock_guard<std::mutex> l(m_);
        if (!adc_.empty()) skipped_++;
        adc_.swap(m);
    }
    cv_.notify_one();
}

std::string LiveTap::stats_line(double t) const {
    char b[160];
    std::snprintf(b, sizeof b, "stats v1 tap t=%.3f sent=%llu skipped=%llu adc_sent=%llu\n", t,
                  static_cast<unsigned long long>(sent()), static_cast<unsigned long long>(skipped()),
                  static_cast<unsigned long long>(adc_sent()));
    return b;
}

void LiveTap::disable(const std::string& why) {
    if (disabled_.exchange(true)) return;
    log_warn("live tap disabled: ", why, "; the run continues without it");
    std::lock_guard<std::mutex> l(m_);
    points_.clear();
    adc_.clear();
}

bool LiveTap::write_all(const std::vector<uint8_t>& msg) {
    size_t off = 0;
    while (off < msg.size()) {
        if (stop_flag_.load()) return false;
        const ssize_t n = ::write(fd_, msg.data() + off, msg.size() - off);
        if (n > 0) {
            off += static_cast<size_t>(n);
        } else if (n < 0 && errno == EINTR) {
            continue;
        } else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            pollfd p{fd_, POLLOUT, 0};
            ::poll(&p, 1, 100);
            if (p.revents & (POLLERR | POLLHUP)) {
                disable("the reader closed the pipe");
                return false;
            }
        } else {
            disable(std::string("write failed: ") + std::strerror(errno));
            return false;
        }
    }
    return true;
}

void LiveTap::run() {
    std::vector<uint8_t> msg;
    bool last_was_points = false;
    for (;;) {
        bool is_adc = false, is_hello = false;
        {
            std::unique_lock<std::mutex> l(m_);
            cv_.wait(l, [this] { return stopping_ || !hello_.empty() || !points_.empty() || !adc_.empty(); });
            if (stopping_ || disabled_.load()) return;
            if (!hello_.empty()) {
                msg.swap(hello_);
                is_hello = true;
            } else if (!points_.empty() && !(last_was_points && !adc_.empty())) {
                msg.swap(points_);  // alternate with adc when both wait, so neither starves
            } else {
                msg.swap(adc_);
                is_adc = true;
            }
        }
        last_was_points = !is_adc && !is_hello;
        if (!write_all(msg)) return;
        if (is_adc) adc_sent_++;
        else if (!is_hello) sent_++;
        msg.clear();
    }
}

}  // namespace radar
}  // namespace cpsl
