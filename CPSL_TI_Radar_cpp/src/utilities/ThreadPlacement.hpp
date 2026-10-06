#ifndef CPSL_RADAR_THREAD_PLACEMENT_HPP
#define CPSL_RADAR_THREAD_PLACEMENT_HPP

// CPU affinity and real-time priority for the driver's threads (design P11,
// directive core-15): the DCA1000 RX thread (runtime.rx_cpu / rx_priority)
// and the DCA worker thread (runtime.worker_cpu / worker_priority).
//
// cpu -1 (the key null or unset) leaves the thread on every CPU; priority
// 1..99 asks for SCHED_RR at that priority (0 leaves the scheduling alone).
// Neither failure is an error: the thread keeps running where and how it
// was, and one warning says why. SCHED_RR needs cap_sys_nice (or an rtprio
// limit); the warning names tools/setup/host_setup.py --apply, which grants it.

#include <pthread.h>
#include <sched.h>

#include <cstdint>

namespace cpsl {
namespace radar {

struct ThreadPlacement {
    int cpu = -1;           // pin to this CPU; -1 = not pinned
    uint32_t priority = 0;  // SCHED_RR priority 1..99; 0 = unchanged
};

struct PlacementResult {
    bool pinned = false;      // affinity set to {cpu}
    bool prioritized = false; // SCHED_RR set
    int affinity_error = 0;   // errno-style code from pthread_setaffinity_np (0 = none / not asked)
    int priority_error = 0;   // from pthread_setschedparam (EPERM: no cap_sys_nice)
};

// The pthread calls, replaceable in tests (the defaults are the real ones).
using SetSchedFn = int (*)(pthread_t, int, const sched_param*);
using SetAffinityFn = int (*)(pthread_t, size_t, const cpu_set_t*);

// Apply `p` to thread `t`; `name` is used in the log lines ("DCA1000 RX").
PlacementResult apply_thread_placement(pthread_t t, const ThreadPlacement& p, const char* name,
                                       SetSchedFn set_sched = nullptr, SetAffinityFn set_affinity = nullptr);

}  // namespace radar
}  // namespace cpsl

#endif
