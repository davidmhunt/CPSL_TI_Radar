#declare packages and dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(SerialStreamer SerialStreamer.cpp)

#link libraries
target_link_libraries(SerialStreamer PUBLIC Utilities
                                    PUBLIC Threads::Threads)