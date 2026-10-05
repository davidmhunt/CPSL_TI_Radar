#ifndef CPSL_RADAR_LOG_HPP
#define CPSL_RADAR_LOG_HPP

// Library logging (driver v2 design §3). Every message the driver library
// emits goes through one process-wide sink, filtered by one process-wide
// level:
//   - The level defaults to info. Radar::open sets it from the system
//     config's runtime.log_level; set_log_level() changes it at any time.
//     A message is passed to the sink only if its level is at or above the
//     current one (error < warn < info < debug, debug the most verbose).
//   - The default sink writes one line per message to stderr; warn and error
//     messages are prefixed "warning: " / "error: ". set_log_sink() replaces
//     it (nullptr restores the default).
// Both calls are thread-safe; the sink is called under a lock, one message
// at a time, from whichever driver thread logged it.

#include <functional>
#include <sstream>
#include <string>

namespace cpsl {
namespace radar {

enum class LogLevel { error, warn, info, debug };
const char* to_string(LogLevel v);

using LogSink = std::function<void(LogLevel, const std::string&)>;

void set_log_sink(LogSink sink);
void set_log_level(LogLevel level);
LogLevel log_level();

// true if a message at `level` reaches the sink (cheap: one atomic load)
bool log_enabled(LogLevel level);

// Pass `message` to the sink if `level` is enabled.
void log_message(LogLevel level, const std::string& message);

// Format the arguments with operator<< only when `level` is enabled.
template <class... Args>
void log_at(LogLevel level, const Args&... args) {
    if (!log_enabled(level)) return;
    std::ostringstream o;
    (o << ... << args);
    log_message(level, o.str());
}

template <class... Args>
void log_error(const Args&... args) { log_at(LogLevel::error, args...); }
template <class... Args>
void log_warn(const Args&... args) { log_at(LogLevel::warn, args...); }
template <class... Args>
void log_info(const Args&... args) { log_at(LogLevel::info, args...); }
template <class... Args>
void log_debug(const Args&... args) { log_at(LogLevel::debug, args...); }

}  // namespace radar
}  // namespace cpsl

#endif
