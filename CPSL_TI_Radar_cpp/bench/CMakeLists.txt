# bench_pipeline: hardware-free replay benchmark of FrameAssembler + ADC
# converter (design §5, directive core-09). Build Release for real numbers:
#   cmake -S CPSL_TI_Radar_cpp -B <dir> -DCMAKE_BUILD_TYPE=Release
#   ctest --test-dir <dir> -L bench --verbose     (or run <dir>/bench/bench_pipeline)
add_executable(bench_pipeline bench_pipeline.cpp)
target_include_directories(bench_pipeline PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(bench_pipeline PRIVATE FrameAssembler ADCCubeConverter Utilities)
target_compile_definitions(bench_pipeline PRIVATE
    CONFIG_DIR="${PROJECT_SOURCE_DIR}/config"
    BENCH_BUILD_TYPE="$<CONFIG>")

# Registered with ctest only when ctest is asked for the bench label
# (ctest -L bench / --label-regex bench), so the default ctest run never
# starts it. ctest has no default label filter, so this script inspects
# ctest's own command line (Linux /proc; design D3) when it loads the tests.
file(GENERATE OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/bench_ctest.cmake CONTENT [=[
set(_cpsl_want_bench FALSE)
if(EXISTS /proc/self/cmdline)
  file(STRINGS /proc/self/cmdline _cpsl_argv)
  set(_cpsl_prev "")
  foreach(_cpsl_a IN LISTS _cpsl_argv)
    set(_cpsl_re "")
    if(_cpsl_prev MATCHES "^(-L|--label-regex)$")
      set(_cpsl_re "${_cpsl_a}")
    elseif(_cpsl_a MATCHES "^-L(.+)$" OR _cpsl_a MATCHES "^--label-regex=(.+)$")
      set(_cpsl_re "${CMAKE_MATCH_1}")
    endif()
    if(NOT _cpsl_re STREQUAL "" AND "bench" MATCHES "${_cpsl_re}")
      set(_cpsl_want_bench TRUE)
    endif()
    set(_cpsl_prev "${_cpsl_a}")
  endforeach()
endif()
if(_cpsl_want_bench)
  add_test(bench_pipeline "$<TARGET_FILE:bench_pipeline>")
  set_tests_properties(bench_pipeline PROPERTIES LABELS bench TIMEOUT 600)
endif()
]=])
set_property(DIRECTORY APPEND PROPERTY TEST_INCLUDE_FILES ${CMAKE_CURRENT_BINARY_DIR}/bench_ctest.cmake)
