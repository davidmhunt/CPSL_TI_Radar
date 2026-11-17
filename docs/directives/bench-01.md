# bench-01: Silence the -Wmismatched-new-delete warning in bench_pipeline
Status: approved
Node: any
Verify: ./run cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build-werror -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-Werror=mismatched-new-delete && ./run cmake --build CPSL_TI_Radar_cpp/build-werror --target bench_pipeline --parallel 8 && ./run tools/check.sh
Hardware: none

## Goal
A Release build of `bench_pipeline` emits no `-Wmismatched-new-delete` warning, and the benchmark's
generated code is unchanged. It holds when the target builds with that warning promoted to an error
and the bench reports the same allocs/frame as before the change.

## Background
`CPSL_TI_Radar_cpp/bench/bench_pipeline.cpp:87-100` replaces the global `operator new`/`delete`
with `std::malloc`/`std::free` wrappers to count allocations. The pairing is correct. GCC inlines
the replacement `operator new` at call sites, then sees the sized `operator delete` (line 99) pass
that pointer to `free` and reports a mismatch. The warning is a false positive for replacement
allocators.

## Steps
1. Before editing, reproduce: configure `CPSL_TI_Radar_cpp/build-werror` as in `Verify:` and build
   the `bench_pipeline` target. Record the exact diagnostic text and compiler version in the Log.
   If the build does not fail, stop and report (the warning then depends on a compiler or flag the
   dev container does not have, and `Verify:` needs revisiting with the user).
2. Run the bench from the existing Release build
   (`./run ctest --test-dir CPSL_TI_Radar_cpp/build -C bench -L bench --verbose`) and save the
   allocs/frame figures to the Log as the baseline.
3. In `bench_pipeline.cpp`, wrap the four `operator delete` definitions (lines 97-100) in
   `#pragma GCC diagnostic push` / `#pragma GCC diagnostic ignored "-Wmismatched-new-delete"` /
   `#pragma GCC diagnostic pop`, with a short comment saying the malloc/free pairing is intended
   and the warning is a false positive for replacement allocators. Guard the pragmas so Clang does
   not raise `-Wunknown-warning-option` (`#if defined(__GNUC__) && !defined(__clang__)`). Change
   nothing else in the file: no attributes, no signature changes, no reordering.
4. If the diagnostic from step 1 is attributed to a call site outside lines 97-100 so that the
   pragma there does not silence it, stop and report rather than widening the suppression or
   switching to `noinline`.
5. Rebuild and rerun the bench as in step 2. The allocs/frame figures must equal the baseline;
   record both in the Log. Timings are not compared (run-to-run noise); nothing goes into
   `docs/RESULTS.md`.
6. Run the `Verify:` command.

## Out of scope
- Any change to how the bench counts allocations, or to its kernels, timing or output.
- `__attribute__((noinline))` on the operators, `-fno-inline`, or a target-wide `-Wno-...` flag:
  the first two change codegen, the third hides future real mismatches in the bench.
- Adding `-Werror` to the normal build or to `tools/check.sh`.
- Adding aligned or nothrow `operator new`/`delete` overloads.
- Other warnings in the tree.

## Log
(execution appends here: commits, Verify results, verifier verdict, PR link, blockers)
