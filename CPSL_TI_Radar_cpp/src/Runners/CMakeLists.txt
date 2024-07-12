
#define dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(DCA1000Runner DCA1000Runner.cpp)

#link libraries
target_link_libraries(DCA1000Runner     PRIVATE Utilities
                                        PRIVATE CLIController
                                        PRIVATE DCA1000Commands
                                        PRIVATE DCA1000Handler
                                        PRIVATE Threads::Threads)