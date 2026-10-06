// Thread placement (design P11, directive core-15): runtime.rx_cpu /
// worker_cpu pin a thread, rx_priority / worker_priority ask for SCHED_RR.
// Hardware- and privilege-free: affinity is real (any process may narrow its
// own threads' CPU set); SCHED_RR goes through a fake pthread_setschedparam,
// so the test checks what is requested and the warning on EPERM.
#include "test_harness.hpp"
#include "ThreadPlacement.hpp"

#include <cerrno>
#include <condition_variable>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "Log.hpp"

using cpsl::radar::apply_thread_placement;
using cpsl::radar::LogLevel;
using cpsl::radar::PlacementResult;
using cpsl::radar::ThreadPlacement;

namespace {

struct Captured {
    std::vector<std::string> warns;
    Captured() {
        cpsl::radar::set_log_sink([this](LogLevel l, const std::string& m) {
            if (l == LogLevel::warn) warns.push_back(m);
        });
    }
    ~Captured() { cpsl::radar::set_log_sink(nullptr); }
};

int g_policy = -1, g_priority = -1, g_calls = 0, g_result = 0;
int fake_sched(pthread_t, int policy, const sched_param* sp) {
    g_calls++;
    g_policy = policy;
    g_priority = sp->sched_priority;
    return g_result;
}

int g_affinity_calls = 0;
int counting_affinity(pthread_t, size_t, const cpu_set_t*) {
    g_affinity_calls++;
    return 0;
}

// a thread that waits until released, so its affinity can be read back
struct Parked {
    std::mutex m;
    std::condition_variable cv;
    bool go = false;
    std::thread t{[this] {
        std::unique_lock<std::mutex> l(m);
        cv.wait(l, [this] { return go; });
    }};
    ~Parked() {
        {
            std::lock_guard<std::mutex> l(m);
            go = true;
        }
        cv.notify_all();
        t.join();
    }
};

}  // namespace

TEST_CASE(cpu_pins_the_thread_to_that_cpu) {
    Parked p;
    const PlacementResult r = apply_thread_placement(p.t.native_handle(), ThreadPlacement{0, 0}, "test");
    CHECK(r.pinned);
    CHECK_EQ(r.affinity_error, 0);
    cpu_set_t set;
    CPU_ZERO(&set);
    CHECK_EQ(pthread_getaffinity_np(p.t.native_handle(), sizeof(set), &set), 0);
    CHECK_EQ(CPU_COUNT(&set), 1);
    CHECK(CPU_ISSET(0, &set));
}

TEST_CASE(unset_keys_change_nothing) {
    g_calls = 0;
    g_affinity_calls = 0;
    Captured log;
    const PlacementResult r =
        apply_thread_placement(pthread_self(), ThreadPlacement{-1, 0}, "test", fake_sched, counting_affinity);
    CHECK(!r.pinned && !r.prioritized);
    CHECK_EQ(g_calls, 0);
    CHECK_EQ(g_affinity_calls, 0);
    CHECK(log.warns.empty());
}

TEST_CASE(priority_requests_sched_rr_and_eperm_is_a_warning_with_the_hint) {
    Captured log;
    g_calls = 0;
    g_result = EPERM;  // no cap_sys_nice
    const PlacementResult r =
        apply_thread_placement(pthread_self(), ThreadPlacement{-1, 42}, "DCA1000 RX", fake_sched, counting_affinity);
    CHECK_EQ(g_calls, 1);
    CHECK_EQ(g_policy, SCHED_RR);
    CHECK_EQ(g_priority, 42);
    CHECK(!r.prioritized);
    CHECK_EQ(r.priority_error, EPERM);
    CHECK_EQ(log.warns.size(), static_cast<size_t>(1));
    if (!log.warns.empty()) {
        CHECK(log.warns[0].find("DCA1000 RX") != std::string::npos);
        CHECK(log.warns[0].find("SCHED_RR 42") != std::string::npos);
        CHECK(log.warns[0].find("host_setup.py --apply") != std::string::npos);
    }
    // granted: no warning
    g_result = 0;
    log.warns.clear();
    const PlacementResult ok =
        apply_thread_placement(pthread_self(), ThreadPlacement{-1, 99}, "DCA worker", fake_sched, counting_affinity);
    CHECK(ok.prioritized);
    CHECK_EQ(g_priority, 99);
    CHECK(log.warns.empty());
}

TEST_CASE(real_sched_rr_is_either_granted_or_a_warning) {
    // whatever this host allows, the call never fails the caller
    Captured log;
    Parked p;
    const PlacementResult r = apply_thread_placement(p.t.native_handle(), ThreadPlacement{-1, 1}, "test");
    CHECK(r.prioritized || (r.priority_error != 0 && log.warns.size() == 1));
}

TEST_CASE(a_cpu_out_of_range_is_a_warning) {
    Captured log;
    Parked p;
    const PlacementResult r = apply_thread_placement(p.t.native_handle(), ThreadPlacement{1023, 0}, "test");
    CHECK(!r.pinned);
    CHECK(r.affinity_error != 0);
    CHECK_EQ(log.warns.size(), static_cast<size_t>(1));
}

TEST_MAIN()
