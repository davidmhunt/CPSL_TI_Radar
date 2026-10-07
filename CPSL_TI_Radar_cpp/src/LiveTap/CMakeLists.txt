#live tap (gui-36): the driver's optional point-cloud / ADC feed to an inherited pipe fd;
#used by main.cpp only (Radar does not know about it)
find_package(Threads REQUIRED)

add_library(LiveTap LiveTap.cpp)

target_include_directories(LiveTap PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/LiveTap>
)

target_link_libraries(LiveTap PUBLIC Radar
                              PUBLIC Threads::Threads)
