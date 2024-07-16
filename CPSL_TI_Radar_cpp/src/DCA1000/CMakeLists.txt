
#add libraries
add_library(DCA1000Commands DCA1000Commands.cpp)
add_library(DCA1000Handler  DCA1000Handler.cpp)

#link libraries
target_link_libraries(DCA1000Handler    PUBLIC Utilities
                                        PUBLIC DCA1000Commands)