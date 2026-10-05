#include "Log.hpp"

#include <atomic>
#include <iostream>
#include <mutex>

namespace cpsl {
namespace radar {

namespace {

std::atomic<int> g_level{static_cast<int>(LogLevel::info)};

std::mutex& sink_mutex() {
    static std::mutex m;
    return m;
}

LogSink& custom_sink() {
    static LogSink s;
    return s;
}

// The only place in the library that writes to a standard stream.
void default_sink(LogLevel level, const std::string& message) {
    const char* prefix = level == LogLevel::error ? "error: " : level == LogLevel::warn ? "warning: " : "";
    std::cerr << prefix << message << '\n' << std::flush;
}

}  // namespace

const char* to_string(LogLevel v) {
    switch (v) {
        case LogLevel::error: return "error";
        case LogLevel::warn: return "warn";
        case LogLevel::info: return "info";
        case LogLevel::debug: return "debug";
    }
    return "?";
}

void set_log_sink(LogSink sink) {
    std::lock_guard<std::mutex> lock(sink_mutex());
    custom_sink() = std::move(sink);
}

void set_log_level(LogLevel level) { g_level.store(static_cast<int>(level), std::memory_order_relaxed); }

LogLevel log_level() { return static_cast<LogLevel>(g_level.load(std::memory_order_relaxed)); }

bool log_enabled(LogLevel level) {
    return static_cast<int>(level) <= g_level.load(std::memory_order_relaxed);
}

void log_message(LogLevel level, const std::string& message) {
    if (!log_enabled(level)) return;
    std::lock_guard<std::mutex> lock(sink_mutex());
    try {
        if (custom_sink()) {
            custom_sink()(level, message);
        } else {
            default_sink(level, message);
        }
    } catch (...) {
        // a throwing sink must not take a driver thread down
    }
}

}  // namespace radar
}  // namespace cpsl
