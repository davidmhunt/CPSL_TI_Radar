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

# Add the executables
add_executable(CPSL_TI_Radar_CPP main.cpp)

# Bake in the absolute path to the default config at build time so the binary
# works from any working directory, not just build/.
target_compile_definitions(CPSL_TI_Radar_CPP PRIVATE
    DEFAULT_CONFIG_PATH="${CMAKE_CURRENT_SOURCE_DIR}/config/system/front_radar_IWR1843_stress_test.json"
)

# Perform linking
target_link_libraries(CPSL_TI_Radar_CPP PRIVATE Runner)

# Install header files
install(DIRECTORY ${PROJECT_SOURCE_DIR}/src/
        DESTINATION include/${PROJECT_NAME}
        FILES_MATCHING PATTERN "*.hpp" PATTERN "*.h"
)

# Install libraries
install(TARGETS nlohmann_json Utilities CLIController SerialStreamer DCA1000Handler ADCCubeConverter FrameAssembler DCA1000Socket Runner TLVProcessing DCA1000Commands driver
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

# Set CPACK variables
set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)
