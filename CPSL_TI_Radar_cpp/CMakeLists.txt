cmake_minimum_required(VERSION 3.11.0)
project(CPSL_TI_Radar_CPP VERSION 0.1.0)

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

# Add the executables
add_executable(CPSL_TI_Radar_CPP main.cpp)
add_executable(MAIN_NO_RUNNER main_no_runner.cpp)

# Perform linking
target_link_libraries(CPSL_TI_Radar_CPP PRIVATE Runner)
target_link_libraries(MAIN_NO_RUNNER PRIVATE Utilities
                                        PRIVATE CLIController
                                        PRIVATE SerialStreamer
                                        PRIVATE DCA1000Handler
                                        PRIVATE DCA1000Runner)

# Include directories - library directories were already exported and don't need to be added
                 
# Install header files
install(DIRECTORY ${PROJECT_SOURCE_DIR}/src/
        DESTINATION include/${PROJECT_NAME}
        FILES_MATCHING PATTERN "*.hpp" PATTERN "*.h"
)

# Install libraries
install(TARGETS nlohmann_json Utilities CLIController SerialStreamer DCA1000Handler DCA1000Runner Runner TLVProcessing DCA1000Commands
        EXPORT export_${PROJECT_NAME}
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin
)

# Export the installed libraries and headers for downstream use
install(EXPORT export_${PROJECT_NAME}
        FILE ${PROJECT_NAME}Targets.cmake
        NAMESPACE ${PROJECT_NAME}::
        DESTINATION lib/cmake/${PROJECT_NAME}
)

# Generate and install the package configuration file
include(CMakePackageConfigHelpers)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}ConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)

configure_package_config_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/cmake/Config.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake
  INSTALL_DESTINATION lib/cmake/${PROJECT_NAME}
)

install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}ConfigVersion.cmake
  DESTINATION lib/cmake/${PROJECT_NAME}
)

# Set CPACK variables
set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)
