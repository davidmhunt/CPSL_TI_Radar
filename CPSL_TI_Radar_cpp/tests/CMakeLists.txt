# Hardware-free unit tests (ctest). No test framework dependency: every test
# executable includes test_harness.hpp and is registered with one add_test.
#
# Run:  ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure

get_filename_component(CPP_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

# add_driver_test(<name> LIBS <targets...>)
# Include directories come from the linked driver targets.
function(add_driver_test name)
    cmake_parse_arguments(T "" "" "LIBS" ${ARGN})
    add_executable(${name} ${name}.cpp)
    target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_LIST_DIR})
    target_link_libraries(${name} PRIVATE ${T_LIBS})
    target_compile_definitions(${name} PRIVATE
        TEST_DATA_DIR="${CMAKE_CURRENT_LIST_DIR}/data"
        CONFIG_DIR="${CPP_ROOT}/config"
        TEST_TMP_DIR="${CMAKE_CURRENT_BINARY_DIR}")
    add_test(NAME ${name} COMMAND ${name})
endfunction()

add_driver_test(test_radar_config_reader   LIBS Utilities)
add_driver_test(test_system_config_v2     LIBS Utilities)
add_driver_test(test_dca1000_commands      LIBS DCA1000Commands)
add_driver_test(test_frame_assembler       LIBS FrameAssembler)
add_driver_test(test_adc_cube_converter    LIBS ADCCubeConverter)
add_driver_test(test_tlv_processing        LIBS TLVProcessing)
add_driver_test(test_serial_streamer_frames LIBS SerialStreamer)
add_driver_test(test_board_descriptor     LIBS BoardDescriptor)
add_driver_test(test_dca_frame_publish    LIBS DCA1000Handler)
add_driver_test(test_dca_file_flush      LIBS DCA1000Handler)
add_driver_test(test_stop_signal         LIBS Utilities)
add_driver_test(test_cli_stop            LIBS Radar util)
add_driver_test(test_cli_echo            LIBS Radar util)
add_driver_test(test_log                 LIBS Utilities)
add_driver_test(test_radar_config        LIBS Utilities)
add_driver_test(test_radar_e2e_fake      LIBS Radar)
add_driver_test(test_dca1000_socket      LIBS DCA1000Socket)
add_driver_test(test_thread_placement    LIBS Log)
add_driver_test(test_uart_parse          LIBS TLVProcessing Utilities)
add_driver_test(test_radar_serial_fake   LIBS Radar)
add_driver_test(test_live_tap            LIBS LiveTap)
# a handler that exits (even with status 0) must not count as a pass
set_tests_properties(test_stop_signal PROPERTIES
                     PASS_REGULAR_EXPRESSION "cases, [0-9]+ checks, 0 failures")

# The driver's --validate path over every tracked system config (and a v1
# fixture, which must be rejected with the migration hint).
get_filename_component(REPO_ROOT "${CPP_ROOT}/.." ABSOLUTE)
add_test(NAME test_validate_all_configs
         COMMAND ${CMAKE_COMMAND}
                 -DDRIVER=$<TARGET_FILE:CPSL_TI_Radar_CPP>
                 -DCONFIG_DIR=${CPP_ROOT}/config
                 -DV1_FIXTURE=${REPO_ROOT}/tests/fixtures/v1_configs/front_radar_IWR1843_stress_test_baseline.json
                 -DTMP_DIR=${CMAKE_CURRENT_BINARY_DIR}/validate_tmp
                 -P ${CMAKE_CURRENT_LIST_DIR}/validate_all_configs.cmake)
