

#declare packages and dependencies
find_package(Threads REQUIRED)


#add libraries
add_library(CLIController CLIController.cpp)

#link libraries
target_link_libraries(CLIController PUBLIC Utilities
                                    PUBLIC Threads::Threads)