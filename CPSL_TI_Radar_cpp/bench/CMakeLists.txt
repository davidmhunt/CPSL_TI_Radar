# bench_pipeline: hardware-free replay benchmark of FrameAssembler + ADC
# converter (design §5, directive core-09). Build Release for real numbers:
#   cmake -S CPSL_TI_Radar_cpp -B <dir> -DCMAKE_BUILD_TYPE=Release
#   ctest --test-dir <dir> -C bench -L bench --verbose   (or run <dir>/bench/bench_pipeline)
add_executable(bench_pipeline bench_pipeline.cpp)
target_include_directories(bench_pipeline PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(bench_pipeline PRIVATE DCA1000Handler FrameAssembler ADCCubeConverter Utilities)
target_compile_definitions(bench_pipeline PRIVATE
    CONFIG_DIR="${PROJECT_SOURCE_DIR}/config"
    BENCH_BUILD_TYPE="$<CONFIG>")

# Registered only for the "bench" ctest configuration, so a plain
# `ctest --test-dir <dir>` never runs it (it is not even listed). Run it with:
#   ctest --test-dir <dir> -C bench -L bench --verbose
add_test(NAME bench_pipeline COMMAND bench_pipeline CONFIGURATIONS bench)
set_tests_properties(bench_pipeline PROPERTIES LABELS bench TIMEOUT 600)

# bench_latency: frame complete -> Radar::next_adc_frame return latency over
# fake transports (directive core-14 P7). Not a ctest; run it directly:
#   <dir>/bench/bench_latency [--frames N] [--period-ms N]
add_executable(bench_latency bench_latency.cpp)
target_link_libraries(bench_latency PRIVATE Radar)
target_compile_definitions(bench_latency PRIVATE CONFIG_DIR="${PROJECT_SOURCE_DIR}/config")

# bench_serial_latency: serial TLV frame latency over a pty, last byte of a
# frame written -> Radar::next_point_cloud return (directive core-16 P8).
# Run it directly for the numbers:
#   <dir>/bench/bench_serial_latency [--frames N] [--period-ms N] [--points N]
# A short run is also a plain ctest test: it fails if any frame is missing or
# is delivered after the next frame's magic word was written.
add_executable(bench_serial_latency bench_serial_latency.cpp)
target_link_libraries(bench_serial_latency PRIVATE Radar util)
target_compile_definitions(bench_serial_latency PRIVATE CONFIG_DIR="${PROJECT_SOURCE_DIR}/config")
add_test(NAME test_serial_latency_pty COMMAND bench_serial_latency --frames 40 --period-ms 25)
set_tests_properties(test_serial_latency_pty PROPERTIES TIMEOUT 60)
