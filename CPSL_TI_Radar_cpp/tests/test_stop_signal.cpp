// SIGINT/SIGTERM set a stop flag and return; they never end the process
// (directive core-11 Step 5). The old handler called exit(0), which skipped
// the destructors and left adc_data.bin short (RESULTS.md Finding 1).
//
// Registered with PASS_REGULAR_EXPRESSION on the harness summary line, so a
// handler that exits (even with status 0) fails the test.
#include "test_harness.hpp"
#include "StopSignal.hpp"

#include <csignal>

static bool handler_is_default(int sig) {
    struct sigaction cur {};
    sigaction(sig, nullptr, &cur);
    return cur.sa_handler == SIG_DFL;
}

TEST_CASE(sigint_sets_the_flag_and_returns) {
    cpsl::radar::clear_stop_request();
    CHECK(cpsl::radar::install_stop_signal_handlers());
    CHECK(!cpsl::radar::stop_requested());
    CHECK(!handler_is_default(SIGINT));
    CHECK_EQ(std::raise(SIGINT), 0);
    // still running: the handler did not exit
    CHECK(cpsl::radar::stop_requested());
    // SA_RESETHAND: a second Ctrl-C would get the default action
    CHECK(handler_is_default(SIGINT));
}

TEST_CASE(sigterm_sets_the_flag_and_returns) {
    cpsl::radar::clear_stop_request();
    CHECK(cpsl::radar::install_stop_signal_handlers());
    CHECK_EQ(std::raise(SIGTERM), 0);
    CHECK(cpsl::radar::stop_requested());
    // leave SIGINT/SIGTERM handled so nothing here can kill the test
    CHECK(cpsl::radar::install_stop_signal_handlers());
}

TEST_CASE(request_and_clear) {
    cpsl::radar::clear_stop_request();
    CHECK(!cpsl::radar::stop_requested());
    cpsl::radar::request_stop();
    CHECK(cpsl::radar::stop_requested());
    cpsl::radar::clear_stop_request();
    CHECK(!cpsl::radar::stop_requested());
}

TEST_MAIN()
