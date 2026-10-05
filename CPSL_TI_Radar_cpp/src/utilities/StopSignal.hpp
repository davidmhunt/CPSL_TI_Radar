#ifndef CPSL_RADAR_STOP_SIGNAL_HPP
#define CPSL_RADAR_STOP_SIGNAL_HPP

// SIGINT/SIGTERM -> stop request. The handler only sets a lock-free atomic
// flag (async-signal-safe); the main loop polls stop_requested() and shuts
// the driver down normally, so threads are joined, sensorStop/recordStop are
// sent and the output files are flushed and closed. The handler is installed
// with SA_RESETHAND: a second Ctrl-C gets the default action, an escape
// hatch if the clean stop itself hangs.

namespace cpsl {
namespace radar {

// Install the handler for SIGINT and SIGTERM. Returns false if sigaction fails.
bool install_stop_signal_handlers();

// True once SIGINT or SIGTERM has arrived (or request_stop() was called).
bool stop_requested();

void request_stop();
void clear_stop_request();

}  // namespace radar
}  // namespace cpsl

#endif
