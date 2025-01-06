cmake_minimum_required(VERSION 3.11.0)
project(CPSL_TI_Radar_CPP VERSION 0.1.0)

#specify required C++ version
set(CMAKE_CXX_STANDARD 11)

include(CTest)
enable_testing()

#add subdirectories
set(JSON_BuildTests OFF CACHE INTERNAL "")
add_subdirectory(include/json)
add_subdirectory(src)

#add the executables
add_executable(CPSL_TI_Radar_CPP main.cpp)
add_executable(MAIN_NO_RUNNER main_no_runner.cpp)

#perform linking
target_link_libraries(CPSL_TI_Radar_CPP   PRIVATE Runner)

target_link_libraries(MAIN_NO_RUNNER    PRIVATE Utilities
                                        PRIVATE CLIController
                                        PRIVATE SerialStreamer
                                        PRIVATE DCA1000Handler
                                        PRIVATE DCA1000Runner)

#include directories
target_include_directories(CPSL_TI_Radar_CPP PRIVATE
                        ${PROJECT_SOURCE_DIR}/src/Runners)

target_include_directories(MAIN_NO_RUNNER PRIVATE
                        ${PROJECT_BINARY_DIR}
                        ${PROJECT_SOURCE_DIR}/src
                        ${PROJECT_SOURCE_DIR}/src/utilities
                        ${PROJECT_SOURCE_DIR}/src/CLIController
                        ${PROJECT_SOURCE_DIR}/src/SerialStreamer
                        ${PROJECT_SOURCE_DIR}/src/DCA1000
                        ${PROJECT_SOURCE_DIR}/src/Runners)

set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)
