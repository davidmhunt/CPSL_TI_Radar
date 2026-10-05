
#define dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(Runner Runner.cpp)

#link libraries
target_link_libraries(Runner            PUBLIC Utilities
                                        PUBLIC CLIController
                                        PUBLIC DCA1000Commands
                                        PUBLIC DCA1000Handler
                                        PUBLIC SerialStreamer
                                        PUBLIC Threads::Threads)