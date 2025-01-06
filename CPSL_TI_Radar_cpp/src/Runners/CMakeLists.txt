
#define dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(DCA1000Runner DCA1000Runner.cpp)
add_library(Runner Runner.cpp)

#link libraries
target_link_libraries(DCA1000Runner     PUBLIC Utilities
                                        PUBLIC CLIController
                                        PUBLIC DCA1000Commands
                                        PUBLIC DCA1000Handler
                                        PUBLIC SerialStreamer
                                        PUBLIC Threads::Threads)

target_link_libraries(Runner            PUBLIC Utilities
                                        PUBLIC CLIController
                                        PUBLIC DCA1000Commands
                                        PUBLIC DCA1000Handler
                                        PUBLIC SerialStreamer
                                        PUBLIC Threads::Threads)