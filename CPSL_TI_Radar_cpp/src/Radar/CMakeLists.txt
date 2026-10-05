#the public API (driver v2 design §3): Radar over CLIController, DCA1000Handler
#(with its PacketSource) and SerialStreamer; RadarConfig/Status/Log come from Utilities
find_package(Threads REQUIRED)

add_library(Radar Radar.cpp)

target_include_directories(Radar PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/Radar>
)

target_link_libraries(Radar PUBLIC Utilities
                            PUBLIC CLIController
                            PUBLIC DCA1000Handler
                            PUBLIC SerialStreamer
                            PUBLIC Threads::Threads)
