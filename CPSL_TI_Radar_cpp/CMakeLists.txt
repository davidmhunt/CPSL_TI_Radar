cmake_minimum_required(VERSION 3.11.0)
project(CPSL_TI_Radar_CPP VERSION 0.1.0)

# Name of the installed CMake package and export namespace:
# find_package(CPSL_TI_Radar) provides CPSL_TI_Radar::driver
set(PKG_NAME CPSL_TI_Radar)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Specify required C++ version
set(CMAKE_CXX_STANDARD 14)

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
