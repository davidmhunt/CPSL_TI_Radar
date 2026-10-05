// Minimal in-tree unit-test harness (no external dependencies).
//
// Usage in a test executable:
//
//   #include "test_harness.hpp"
//   TEST_CASE(my_case) { CHECK_EQ(1 + 1, 2); }
//   TEST_MAIN()
//
// Each executable is one ctest test: it exits non-zero if any CHECK failed or
// a test case threw. KNOWN_BUG records current-but-wrong behaviour: the
// expression is the CORRECT behaviour, which is expected to be false today.
// If the bug gets fixed the check starts failing so the test can be updated.
#ifndef TEST_HARNESS_HPP
#define TEST_HARNESS_HPP

#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace th {

struct Case {
    const char* name;
    void (*fn)();
};

inline std::vector<Case>& registry() {
    static std::vector<Case> r;
    return r;
}

struct Registrar {
    Registrar(const char* name, void (*fn)()) { registry().push_back({name, fn}); }
};

struct Counters {
    int checks = 0;
    int failures = 0;
    int known_bugs = 0;
};

inline Counters& counters() {
    static Counters c;
    return c;
}

template <class T>
std::string show(const T& v) {
    std::ostringstream o;
    o << v;
    return o.str();
}
inline std::string show(unsigned char v) { return std::to_string(static_cast<unsigned>(v)); }
inline std::string show(bool v) { return v ? "true" : "false"; }

inline void fail(const char* file, int line, const std::string& msg) {
    counters().failures++;
    std::cerr << file << ":" << line << ": FAIL: " << msg << std::endl;
}

inline int run_all() {
    for (const Case& c : registry()) {
        int before = counters().failures;
        std::cout << "[ RUN      ] " << c.name << std::endl;
        try {
            c.fn();
        } catch (const std::exception& e) {
            fail(c.name, 0, std::string("uncaught exception: ") + e.what());
        } catch (...) {
            fail(c.name, 0, "uncaught non-std exception");
        }
        std::cout << (counters().failures == before ? "[       OK ] " : "[  FAILED  ] ")
                  << c.name << std::endl;
    }
    std::cout << "\n" << registry().size() << " cases, " << counters().checks << " checks, "
              << counters().failures << " failures, " << counters().known_bugs
              << " known bugs pinned" << std::endl;
    return counters().failures == 0 ? 0 : 1;
}

}  // namespace th

#define TEST_CASE(name)                                          \
    static void name();                                          \
    static th::Registrar registrar_##name(#name, name);          \
    static void name()

#define TEST_MAIN() \
    int main() { return th::run_all(); }

#define CHECK(cond)                                                              \
    do {                                                                         \
        th::counters().checks++;                                                 \
        if (!(cond)) th::fail(__FILE__, __LINE__, "CHECK(" #cond ")");           \
    } while (0)

#define CHECK_EQ(a, b)                                                           \
    do {                                                                         \
        th::counters().checks++;                                                 \
        auto th_a = (a); /* by value: never ODR-uses static const members */     \
        auto th_b = (b);                                                         \
        if (!(th_a == th_b))                                                     \
            th::fail(__FILE__, __LINE__,                                         \
                     std::string("CHECK_EQ(" #a ", " #b ") got ") +              \
                         th::show(th_a) + " vs " + th::show(th_b));              \
    } while (0)

#define CHECK_NEAR(a, b, eps)                                                    \
    do {                                                                         \
        th::counters().checks++;                                                 \
        double th_a = static_cast<double>(a);                                    \
        double th_b = static_cast<double>(b);                                    \
        double th_d = th_a > th_b ? th_a - th_b : th_b - th_a;                   \
        if (!(th_d <= (eps)))                                                    \
            th::fail(__FILE__, __LINE__,                                         \
                     std::string("CHECK_NEAR(" #a ", " #b ") got ") +            \
                         th::show(th_a) + " vs " + th::show(th_b));              \
    } while (0)

#define CHECK_THROWS(expr, ExType)                                               \
    do {                                                                         \
        th::counters().checks++;                                                 \
        try {                                                                    \
            expr;                                                                \
            th::fail(__FILE__, __LINE__, "CHECK_THROWS(" #expr ") did not throw"); \
        } catch (const ExType&) {                                                \
        } catch (...) {                                                          \
            th::fail(__FILE__, __LINE__,                                         \
                     "CHECK_THROWS(" #expr ") threw a different exception type"); \
        }                                                                        \
    } while (0)

// correct_behaviour is expected to be FALSE while the bug exists.
#define KNOWN_BUG(correct_behaviour, description)                                \
    do {                                                                         \
        th::counters().checks++;                                                 \
        if (correct_behaviour)                                                   \
            th::fail(__FILE__, __LINE__,                                         \
                     std::string("known bug appears FIXED, update the test: ") + \
                         description);                                           \
        else                                                                     \
            th::counters().known_bugs++;                                         \
    } while (0)

#endif  // TEST_HARNESS_HPP
