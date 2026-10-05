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
add_driver_test(test_system_config_reader  LIBS Utilities)
add_driver_test(test_dca1000_commands      LIBS DCA1000Commands)
add_driver_test(test_frame_assembler       LIBS FrameAssembler)
add_driver_test(test_adc_cube_converter    LIBS ADCCubeConverter)
add_driver_test(test_tlv_processing        LIBS TLVProcessing)
add_driver_test(test_serial_streamer_frames LIBS SerialStreamer)
add_driver_test(test_board_descriptor     LIBS BoardDescriptor)
