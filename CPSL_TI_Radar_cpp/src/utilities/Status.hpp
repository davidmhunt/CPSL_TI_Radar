#ifndef CPSL_RADAR_STATUS_HPP
#define CPSL_RADAR_STATUS_HPP

// Status / Result (driver v2 design §3): every fallible library call returns
// one of these instead of throwing, printing or exiting. A Status is "ok"
// when its code is Code::ok; otherwise `message` says what failed and names
// the file, path, port or command involved.

#include <optional>
#include <string>
#include <utility>

namespace cpsl {
namespace radar {

enum class Code {
    ok,
    invalid_config,      // the system config, board descriptor or radar cfg is unusable
    output_dir,          // output.dir cannot be created or written
    open_failed,         // a port or socket could not be opened
    invalid_state,       // call not allowed now (e.g. start() before configure(), or after stop())
    already_configured,  // configure() again on a config_once_per_boot board: nothing sent
    config_rejected,     // a cfg command was not acknowledged
    device_error,        // the DCA1000 did not answer or refused a command
    io_error,            // a read/write on a port failed (e.g. the radar's USB is gone)
    timeout,             // no frame within the requested timeout
    stalled,             // no frame for runtime.stall_timeout_ms while running
    stopped,             // the radar was stopped
    disabled,            // that stream is not enabled in the config
    file_error,          // an output file failed to open, flush or close
    malformed_frame,     // a serial TLV frame failed validation (parse_uart_frame)
};

const char* to_string(Code c);

struct Status {
    Code code = Code::ok;
    std::string message;

    Status() = default;
    Status(Code c, std::string m) : code(c), message(std::move(m)) {}
    static Status ok() { return Status(); }

    explicit operator bool() const { return code == Code::ok; }
    bool operator==(const Status& o) const { return code == o.code && message == o.message; }
    bool operator!=(const Status& o) const { return !(*this == o); }
};

// A value or the Status saying why there is none.
template <class T>
struct Result {
    Status status;
    std::optional<T> value;

    Result(Status s) : status(std::move(s)) {}  // NOLINT: implicit, so `return Status(...)` works
    Result(T v) : value(std::move(v)) {}        // NOLINT

    explicit operator bool() const { return status.code == Code::ok && value.has_value(); }
    T& operator*() { return *value; }
    const T& operator*() const { return *value; }
    T* operator->() { return &*value; }
    const T* operator->() const { return &*value; }
};

inline const char* to_string(Code c) {
    switch (c) {
        case Code::ok: return "ok";
        case Code::invalid_config: return "invalid_config";
        case Code::output_dir: return "output_dir";
        case Code::open_failed: return "open_failed";
        case Code::invalid_state: return "invalid_state";
        case Code::already_configured: return "already_configured";
        case Code::config_rejected: return "config_rejected";
        case Code::device_error: return "device_error";
        case Code::io_error: return "io_error";
        case Code::timeout: return "timeout";
        case Code::stalled: return "stalled";
        case Code::stopped: return "stopped";
        case Code::disabled: return "disabled";
        case Code::file_error: return "file_error";
        case Code::malformed_frame: return "malformed_frame";
    }
    return "?";
}

}  // namespace radar
}  // namespace cpsl

#endif
