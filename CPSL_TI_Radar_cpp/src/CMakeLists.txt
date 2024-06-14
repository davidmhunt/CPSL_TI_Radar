
#add subdirectories
add_subdirectory(utilities)

#add libraries
add_library(CLIController CLIController.cpp)

target_link_libraries(CLIController PRIVATE Utilities)