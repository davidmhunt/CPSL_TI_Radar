cmake_minimum_required(VERSION 3.11.0)
project(CPSL_TI_Radar_CPP VERSION 0.1.0)

#specify required C++ version
set(CMAKE_CXX_STANDARD 11)

include(CTest)
enable_testing()

#add subdirectories
add_subdirectory(src)

#add the executables
add_executable(CPSL_TI_Radar_CPP main.cpp)

#perform linking
target_link_libraries(CPSL_TI_Radar_CPP PRIVATE Utilities)

#include directories
target_include_directories(CPSL_TI_Radar_CPP PRIVATE
                        ${PROJECT_BINARY_DIR}
                        ${PROJECT_SOURCE_DIR}/src
                        ${PROJECT_SOURCE_DIR}/src/utilities)

set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)
