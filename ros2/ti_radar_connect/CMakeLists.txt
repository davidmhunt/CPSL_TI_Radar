cmake_minimum_required(VERSION 3.8)
project(ti_radar_connect)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find packages
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(raw_radar_msgs REQUIRED)

# the v2 driver's tests and bench are not needed to build the node
set(BUILD_TESTING_SAVED ${BUILD_TESTING})
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
# vendor the driver from this repo (ros2/ti_radar_connect -> ../../CPSL_TI_Radar_cpp)
set(TI_RADAR_CPP_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../CPSL_TI_Radar_cpp)
add_subdirectory(${TI_RADAR_CPP_DIR} ${CMAKE_CURRENT_BINARY_DIR}/CPSL_TI_Radar_cpp)
set(BUILD_TESTING ${BUILD_TESTING_SAVED} CACHE BOOL "" FORCE)

#following instructions from: following instructions from: https://docs.ros.org/en/rolling/How-To-Guides/Ament-CMake-Documentation.html
#declare TIRadarCOnnectNode library
add_library(TIRadarConnectNode src/TIRadarConnectNode.cpp)
target_link_libraries(TIRadarConnectNode PUBLIC CPSL_TI_Radar::driver)
ament_target_dependencies(TIRadarConnectNode PUBLIC rclcpp raw_radar_msgs sensor_msgs std_msgs)
target_include_directories(TIRadarConnectNode
  PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include/${PROJECT_NAME}>"
    "$<INSTALL_INTERFACE:include/${PROJECT_NAME}>")
install(
  DIRECTORY include/ti_radar_connect #look to potentially remove this
  DESTINATION include/${PROJECT_NAME}
)
install(
  TARGETS TIRadarConnectNode
  EXPORT export_${PROJECT_NAME}
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION bin
)

ament_export_targets(export_${PROJECT_NAME} HAS_LIBRARY_TARGET)
ament_export_dependencies(rclcpp raw_radar_msgs sensor_msgs std_msgs)
ament_export_include_directories("include/${PROJECT_NAME}")
ament_export_libraries(TIRadarConnectNode)


#declare the executable
add_executable(ti_radar_connect src/ti_radar_connect.cpp)
target_link_libraries(ti_radar_connect PUBLIC TIRadarConnectNode)
ament_target_dependencies(ti_radar_connect PUBLIC rclcpp sensor_msgs)
install(TARGETS
  ti_radar_connect
  DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

# Install launch files.
install(DIRECTORY
  launch
  DESTINATION share/${PROJECT_NAME}/
)

install(DIRECTORY
  ../../CPSL_TI_Radar_cpp/config/system
  DESTINATION share/${PROJECT_NAME}/config
)
install(DIRECTORY
  ../../CPSL_TI_Radar_cpp/config/radar
  DESTINATION share/${PROJECT_NAME}/config
)

# The v2 driver resolves board/firmware descriptors (and cfg limits) relative to the
# system JSON's directory (../boards, ../firmware, ../limits), so they must sit beside
# config/system in the install tree.
foreach(_d boards firmware limits)
  install(DIRECTORY
    ../../CPSL_TI_Radar_cpp/config/${_d}
    DESTINATION share/${PROJECT_NAME}/config
  )
endforeach()

# Install accessible config overrides AFTER submodule configs so same-named
# files here take precedence. Add new configs to config/system/ and config/radar/
# rather than editing the submodule.
install(DIRECTORY
  config/system
  DESTINATION share/${PROJECT_NAME}/config
)
install(DIRECTORY
  config/radar
  DESTINATION share/${PROJECT_NAME}/config
)

ament_package()
