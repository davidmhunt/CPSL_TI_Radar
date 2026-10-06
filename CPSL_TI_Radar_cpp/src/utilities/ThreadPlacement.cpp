#include "ThreadPlacement.hpp"

#include <cerrno>
#include <cstring>

#include "Log.hpp"

namespace cpsl {
namespace radar {

namespace {
int real_set_sched(pthread_t t, int policy, const sched_param* sp) { return pthread_setschedparam(t, policy, sp); }
int real_set_affinity(pthread_t t, size_t n, const cpu_set_t* set) { return pthread_setaffinity_np(t, n, set); }
}  // namespace

PlacementResult apply_thread_placement(pthread_t t, const ThreadPlacement& p, const char* name, SetSchedFn set_sched,
                                       SetAffinityFn set_affinity) {
    if (set_sched == nullptr) set_sched = real_set_sched;
    if (set_affinity == nullptr) set_affinity = real_set_affinity;
    PlacementResult r;
    if (p.cpu >= 0) {
        if (p.cpu >= CPU_SETSIZE) {
            r.affinity_error = EINVAL;
        } else {
            cpu_set_t set;
            CPU_ZERO(&set);
            CPU_SET(p.cpu, &set);
            r.affinity_error = set_affinity(t, sizeof(set), &set);
        }
        if (r.affinity_error == 0) {
            r.pinned = true;
            log_debug(name, " thread pinned to CPU ", p.cpu);
        } else {
            log_warn(name, " thread: could not pin to CPU ", p.cpu, " (", std::strerror(r.affinity_error),
                     "); it runs on any CPU. Check the CPU number against nproc / the cpuset.");
        }
    }
    if (p.priority > 0) {
        sched_param sp{};
        sp.sched_priority = static_cast<int>(p.priority);
        r.priority_error = set_sched(t, SCHED_RR, &sp);
        if (r.priority_error == 0) {
            r.prioritized = true;
            log_debug(name, " thread at SCHED_RR ", p.priority);
        } else if (r.priority_error == EPERM) {
            log_warn(name, " thread: could not set SCHED_RR ", p.priority,
                     " (not permitted); it runs at normal priority. A requested "
                     "real-time priority needs cap_sys_nice or an rtprio limit; "
                     "set the priority to 0 to disable the request");
        } else {
            log_warn(name, " thread: could not set SCHED_RR ", p.priority, " (", std::strerror(r.priority_error),
                     "); it runs at normal priority");
        }
    }
    return r;
}

}  // namespace radar
}  // namespace cpsl
