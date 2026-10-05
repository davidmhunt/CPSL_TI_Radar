cmake_minimum_required(VERSION 3.11.0)
project(CPSL_TI_Radar_CPP VERSION 0.1.0)

# Name of the installed CMake package and export namespace:
# find_package(CPSL_TI_Radar) provides CPSL_TI_Radar::driver
set(PKG_NAME CPSL_TI_Radar)

# Default to an optimized build (core-12). A plain
# `cmake -S CPSL_TI_Radar_cpp -B build` with no -DCMAKE_BUILD_TYPE gives
# Release; an explicit type (-DCMAKE_BUILD_TYPE=Debug, the asan-ubsan preset)
# is left alone. Multi-config generators choose the type at build time.
get_property(_is_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(NOT _is_multi_config AND NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING
      "Build type (default Release; e.g. Debug, RelWithDebInfo)" FORCE)
endif()
if(_is_multi_config)
  message(STATUS "Build type: multi-config generator (${CMAKE_CONFIGURATION_TYPES}); choose with --config")
else()
  message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# C++17 (design D2). The code needs no GNU extensions; CMAKE_CXX_EXTENSIONS
# stays at its default (-std=gnu++17, as gnu++14 before) only because nothing
# needed to change it. Strict -std=c++17 did measure 44% slower on
# bench_pipeline's flat converter kernel (c) (core-10 Log), but that is not a
# strict-mode effect: the kernel's asm is identical with and without
# __STRICT_ANSI__ (core-10 review). It is most likely code layout/alignment on
# a very short memory-bound loop, so it is no reason to avoid strict mode.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Set a default install prefix if not provided by the user
# if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
#     set(DCMAKE_INSTALL_PREFIX "${CMAKE_BINARY_DIR}/install" CACHE PATH "Installation Directory" FORCE)
# endif()

include(CTest)
enable_testing()

# Add subdirectories
set(JSON_BuildTests OFF CACHE INTERNAL "")
add_subdirectory(include/json)
add_subdirectory(src)

# Hardware-free unit tests (run with ctest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()

# Replay benchmark (bench/): built with the tests, run only by ctest -L bench
if(BUILD_TESTING)
  add_subdirectory(bench)
endif()

# Add the executables
add_executable(CPSL_TI_Radar_CPP main.cpp)

# The config is a required argument: CPSL_TI_Radar_CPP <system.json> [--validate]

# Perform linking
target_link_libraries(CPSL_TI_Radar_CPP PRIVATE Runner)

# Install header files
install(DIRECTORY ${PROJECT_SOURCE_DIR}/src/
        DESTINATION include/${PROJECT_NAME}
        FILES_MATCHING PATTERN "*.hpp" PATTERN "*.h"
)

# Install libraries
install(TARGETS nlohmann_json BoardDescriptor Utilities CLIController SerialStreamer DCA1000Handler ADCCubeConverter FrameAssembler DCA1000Socket Runner TLVProcessing DCA1000Commands driver
        EXPORT export_${PKG_NAME}
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin
)

# Export the installed libraries and headers for downstream use
install(EXPORT export_${PKG_NAME}
        FILE ${PKG_NAME}Targets.cmake
        NAMESPACE ${PKG_NAME}::
        DESTINATION lib/cmake/${PKG_NAME}
)

# Generate and install the package configuration file
include(CMakePackageConfigHelpers)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/${PKG_NAME}ConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)

configure_package_config_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/Config.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/${PKG_NAME}Config.cmake
  INSTALL_DESTINATION lib/cmake/${PKG_NAME}
)

install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/${PKG_NAME}Config.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/${PKG_NAME}ConfigVersion.cmake
  DESTINATION lib/cmake/${PKG_NAME}
)

# One-release compatibility package: find_package(CPSL_TI_Radar_CPP) forwards to
# CPSL_TI_Radar and aliases the old CPSL_TI_Radar_CPP:: target names (deprecated)
set(COMPAT_NAME CPSL_TI_Radar_CPP)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/${COMPAT_NAME}ConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)
configure_package_config_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/CompatConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/${COMPAT_NAME}Config.cmake
  INSTALL_DESTINATION lib/cmake/${COMPAT_NAME}
)
install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/${COMPAT_NAME}Config.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/${COMPAT_NAME}ConfigVersion.cmake
  DESTINATION lib/cmake/${COMPAT_NAME}
)

# Set CPACK variables
set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)
