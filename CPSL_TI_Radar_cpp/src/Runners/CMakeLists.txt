#define dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(Runner Runner.cpp)

target_include_directories(Runner PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/Runners>
)

#link libraries
target_link_libraries(Runner            PUBLIC Utilities
                                        PUBLIC CLIController
                                        PUBLIC DCA1000Commands
                                        PUBLIC DCA1000Handler
                                        PUBLIC SerialStreamer
                                        PUBLIC Threads::Threads)
