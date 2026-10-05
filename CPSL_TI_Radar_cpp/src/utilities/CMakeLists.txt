find_package(Boost REQUIRED)

#create the utilities library
add_library(Utilities SystemConfigReader.cpp RadarConfigReader.cpp SerialBaud.cpp SerialBaudTermios2.cpp)

target_include_directories(Utilities PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
)

#link libraries as needed
target_link_libraries(Utilities PUBLIC nlohmann_json::nlohmann_json
                                PUBLIC Boost::boost)
