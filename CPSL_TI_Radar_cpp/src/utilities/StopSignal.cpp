#include "StopSignal.hpp"

#include <atomic>
#include <csignal>

namespace cpsl {
namespace radar {

namespace {

std::atomic<bool> g_stop{false};
static_assert(std::atomic<bool>::is_always_lock_free, "the signal handler needs a lock-free flag");

extern "C" void on_stop_signal(int) { g_stop.store(true, std::memory_order_relaxed); }

}  // namespace

bool install_stop_signal_handlers() {
    struct sigaction sa {};
    sa.sa_handler = on_stop_signal;
    sigemptyset(&sa.sa_mask);
    // SA_RESTART: blocking reads/writes in the driver's threads carry on;
    // SA_RESETHAND: a second signal takes the default action (terminate)
    sa.sa_flags = SA_RESTART | SA_RESETHAND;
    return sigaction(SIGINT, &sa, nullptr) == 0 && sigaction(SIGTERM, &sa, nullptr) == 0;
}

bool stop_requested() { return g_stop.load(std::memory_order_relaxed); }

void request_stop() { g_stop.store(true, std::memory_order_relaxed); }

void clear_stop_request() { g_stop.store(false, std::memory_order_relaxed); }

}  // namespace radar
}  // namespace cpsl
