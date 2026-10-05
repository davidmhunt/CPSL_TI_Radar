# bench_pipeline: hardware-free replay benchmark of FrameAssembler + ADC
# converter (design §5, directive core-09). Build Release for real numbers:
#   cmake -S CPSL_TI_Radar_cpp -B <dir> -DCMAKE_BUILD_TYPE=Release
#   ctest --test-dir <dir> -C bench -L bench --verbose   (or run <dir>/bench/bench_pipeline)
add_executable(bench_pipeline bench_pipeline.cpp)
target_include_directories(bench_pipeline PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(bench_pipeline PRIVATE FrameAssembler ADCCubeConverter Utilities)
target_compile_definitions(bench_pipeline PRIVATE
    CONFIG_DIR="${PROJECT_SOURCE_DIR}/config"
    BENCH_BUILD_TYPE="$<CONFIG>")

# Registered only for the "bench" ctest configuration, so a plain
# `ctest --test-dir <dir>` never runs it (it is not even listed). Run it with:
#   ctest --test-dir <dir> -C bench -L bench --verbose
add_test(NAME bench_pipeline COMMAND bench_pipeline CONFIGURATIONS bench)
set_tests_properties(bench_pipeline PROPERTIES LABELS bench TIMEOUT 600)
