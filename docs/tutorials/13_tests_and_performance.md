# 13. Write a test, measure performance

Run from the repository root, with the build from [tutorial 1](01_build_and_host_setup.md).

## Write a test

Each `tests/test_*.cpp` is one executable and one ctest test, using the in-tree harness `tests/test_harness.hpp` (`TEST_CASE`, `CHECK`, `CHECK_EQ`, `TEST_MAIN`). No device is needed: `Radar::open` accepts fake transports (`FakeCli`, `ReplayPacketSource` in `tests/fake_transports.hpp`), and `tests/dca_test_support.hpp` writes a system config and builds a frame's packets. This one pushes a frame through a whole `Radar`; save it as `CPSL_TI_Radar_cpp/tests/test_one_frame.cpp`:

```cpp
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "fake_transports.hpp"
#include "Radar.hpp"

#include <filesystem>

using namespace cpsl::radar;

TEST_CASE(one_frame_through_fake_transports) {
    const std::string out = dca_test::tmp_dir() + "/one_frame";
    std::filesystem::create_directories(out);
    auto cfg = RadarConfig::load(dca_test::write_system_config("one_frame", out, false));
    CHECK(static_cast<bool>(cfg));
    if (!cfg) return;

    auto cli = std::make_shared<FakeCli>();                    // answers every command "Done"
    auto packets = std::make_shared<ReplayPacketSource>();     // packets we push by hand
    auto opened = Radar::open(*cfg, {cli, packets});
    CHECK(static_cast<bool>(opened));
    if (!opened) return;
    Radar& r = **opened;
    CHECK(static_cast<bool>(r.configure()));
    CHECK(static_cast<bool>(r.start()));

    uint32_t seq = 1;
    for (auto& p : dca_test::frame_packets(0, cfg->frame_shape().bytes, 100, seq)) packets->push(p);

    AdcFrame f;
    Status why;
    CHECK(r.next_adc_frame(f, std::chrono::milliseconds(3000), &why));
    CHECK_EQ(f.index, uint64_t(0));
    CHECK_EQ(f.missing_bytes, 0u);
    CHECK_EQ(f.data[0][0][0].real(), int16_t(100));            // every sample was (100, 100)
    CHECK(static_cast<bool>(r.stop()));
}

TEST_MAIN()
```

Register it by adding one line to `CPSL_TI_Radar_cpp/tests/CMakeLists.txt`, next to the other `add_driver_test` lines (`LIBS` names the libraries it links), then re-run the configure step (CMake does not scan for new files):

```bash
sed -i 's/^add_driver_test(test_radar_serial_fake   LIBS Radar)/&\nadd_driver_test(test_one_frame           LIBS Radar)/' CPSL_TI_Radar_cpp/tests/CMakeLists.txt
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j --target test_one_frame
ctest --test-dir CPSL_TI_Radar_cpp/build -R test_one_frame --output-on-failure
```

Expect `100% tests passed`. Record a bug you are not fixing with `KNOWN_BUG(...)`. For a crash or memory bug, run the suite under ASan/UBSan:

```bash
cd CPSL_TI_Radar_cpp && cmake --preset asan-ubsan && cmake --build --preset asan-ubsan -j && ctest --preset asan-ubsan; cd ..
```

Remove the exercise when done: `rm CPSL_TI_Radar_cpp/tests/test_one_frame.cpp && git restore CPSL_TI_Radar_cpp/tests/CMakeLists.txt`.

## Measure performance

Three tools, smallest first. **Replay** (no hardware, Release build): it replays synthetic packets, clean, with drops and with reordering, through the real assembler and converters, and prints frames/s, CPU ns per ADC byte and heap allocations per frame:

```bash
CPSL_TI_Radar_cpp/build/bench/bench_pipeline --frames 400
CPSL_TI_Radar_cpp/build/bench/bench_pipeline --udp --frames 100 --stall-ms 200   # loopback, one consumer stall
```

The second line runs the real receive path over loopback and should report 0 discards and 0 kernel drops.

**Before/after a change.** Moving code can change a short kernel's speed by tens of percent on its own. The gate compares two builds of each tree, the default and the `bench-aligned` preset (`-falign-functions=64 -falign-loops=64`), three interleaved runs each, and fails only if a row is more than 5% slower in **both** builds, allocations per frame rise, or a run is not golden. In each tree (before your change, then after), build both and save the binaries under the names shown, then run:

```bash
cd CPSL_TI_Radar_cpp && cmake --preset bench-aligned && cmake --build --preset bench-aligned -j --target bench_pipeline; cd ..
cp CPSL_TI_Radar_cpp/build/bench/bench_pipeline /tmp/bp_before_default      # after building the "before" tree
cp CPSL_TI_Radar_cpp/build-bench-aligned/bench/bench_pipeline /tmp/bp_before_aligned
# apply your change, rebuild both, copy to /tmp/bp_after_default and /tmp/bp_after_aligned
mkdir -p /tmp/perf
for i in 1 2 3; do for v in before after; do for b in default aligned; do
    /tmp/bp_${v}_${b} --frames 400 > /tmp/perf/p_${v}_${b}_${i}.txt
done; done; done
uv run tools/bench/pipeline_gate.py /tmp/perf/p_*.txt
```

Exit 0 passes; a regression in one build only is printed as layout noise.

**On a board** (needs the board and a DCA1000): follow [`bench_validation.md`](bench_validation.md): it runs the real driver on a board, reads the `stats v1` lines and compares them with the reference numbers in `docs/RESULTS.md`.
