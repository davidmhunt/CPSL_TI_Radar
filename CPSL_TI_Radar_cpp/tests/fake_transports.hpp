// Fake transports for hardware-free tests: a scripted CLI (cpsl::radar::ByteStream)
// and a log capture. Used by test_cli_stop and test_radar_e2e_fake.
#ifndef FAKE_TRANSPORTS_HPP
#define FAKE_TRANSPORTS_HPP

#include <algorithm>
#include <atomic>
#include <boost/system/system_error.hpp>
#include <chrono>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "ByteStream.hpp"
#include "Log.hpp"

// A scripted CLI: every written line is answered with "Done" + the prompt.
// After `fail_after` writes, writes fail: by throwing (as boost::asio::write
// does on an unplugged port), by returning EIO, or by hanging until the
// write's timeout (a wedged CDC device). reply_delay holds a command's reply
// back; prompt_error_on drops one command's prompt and fails the next read.
class FakeCli : public cpsl::radar::ByteStream {
public:
    enum class Fail { none, throw_system_error, return_eio, read_eio, no_reply, write_hangs };
    using clock = std::chrono::steady_clock;

    std::error_code write(const uint8_t* data, size_t len, std::chrono::milliseconds timeout) override {
        std::unique_lock<std::mutex> l(m_);
        const std::string line(reinterpret_cast<const char*>(data), len);
        const std::string cmd = line.substr(0, line.size() - 1);
        attempted.push_back(line);
        write_timeouts.push_back(timeout);
        if (fail != Fail::none && writes_ok >= fail_after) {
            if (fail == Fail::throw_system_error)
                throw boost::system::system_error(boost::system::error_code(EIO, boost::system::system_category()),
                                                  "write");
            if (fail == Fail::return_eio) return std::error_code(EIO, std::system_category());
            if (fail == Fail::write_hangs) {
                l.unlock();
                std::this_thread::sleep_for(timeout);  // never completes: the timeout ends it
                return std::make_error_code(std::errc::timed_out);
            }
            if (fail == Fail::no_reply) { writes_ok++; return {}; }
            // read_eio: the write lands, the read fails
            writes_ok++;
            read_error_ = true;
            return {};
        }
        writes_ok++;
        auto d = reply_delay.find(cmd);
        const clock::time_point at = clock::now() + (d == reply_delay.end() ? std::chrono::milliseconds(0) : d->second);
        if (cmd == prompt_error_on) {
            pending_.push_back({at, "\r\n" + cmd + "\r\nDone\r\n"});
            prompt_error_ = true;
        } else {
            pending_.push_back({at, "\r\n" + cmd + "\r\nDone\r\nmmwDemo:/>"});
        }
        return {};
    }

    std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) override {
        n = 0;
        std::unique_lock<std::mutex> l(m_);
        if (read_error_) return std::error_code(EIO, std::system_category());
        if (pending_.empty()) {
            if (prompt_error_) {
                prompt_error_ = false;
                return std::error_code(EIO, std::system_category());
            }
            l.unlock();
            std::this_thread::sleep_for(std::min(timeout, std::chrono::milliseconds(5)));
            return std::make_error_code(std::errc::timed_out);
        }
        const clock::time_point at = pending_.front().first;
        if (clock::now() < at) {
            l.unlock();
            const auto wait = std::min<clock::duration>(timeout, at - clock::now());
            std::this_thread::sleep_for(wait);
            l.lock();
            if (pending_.empty() || clock::now() < pending_.front().first)
                return std::make_error_code(std::errc::timed_out);
        }
        std::string& front = pending_.front().second;
        n = std::min(cap, front.size());
        std::memcpy(buf, front.data(), n);
        front.erase(0, n);
        if (front.empty()) pending_.pop_front();
        return {};
    }

    // how many times `line` (with its newline) was written
    size_t count(const std::string& line) {
        std::lock_guard<std::mutex> l(m_);
        return static_cast<size_t>(std::count(attempted.begin(), attempted.end(), line));
    }
    size_t writes() {
        std::lock_guard<std::mutex> l(m_);
        return attempted.size();
    }

    void fail_from_now(Fail f) {
        std::lock_guard<std::mutex> l(m_);
        fail = f;
        fail_after = writes_ok;
    }

    std::vector<std::string> attempted;
    std::vector<std::chrono::milliseconds> write_timeouts;
    size_t writes_ok = 0;
    Fail fail = Fail::none;
    size_t fail_after = 0;
    std::map<std::string, std::chrono::milliseconds> reply_delay;
    std::string prompt_error_on;

private:
    std::mutex m_;
    std::deque<std::pair<clock::time_point, std::string>> pending_;
    bool read_error_ = false;
    bool prompt_error_ = false;
};

// Collects warn and error messages while alive.
class WarnCapture {
public:
    WarnCapture() {
        cpsl::radar::set_log_sink([this](cpsl::radar::LogLevel l, const std::string& m) {
            if (l == cpsl::radar::LogLevel::warn || l == cpsl::radar::LogLevel::error) {
                std::lock_guard<std::mutex> lock(m_);
                lines.push_back(m);
            }
        });
    }
    ~WarnCapture() { cpsl::radar::set_log_sink(nullptr); }
    std::vector<std::string> get() {
        std::lock_guard<std::mutex> lock(m_);
        return lines;
    }

private:
    std::mutex m_;
    std::vector<std::string> lines;
};

#endif  // FAKE_TRANSPORTS_HPP
