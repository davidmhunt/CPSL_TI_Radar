

#add libraries
add_library(CLIController CLIController.cpp)

#link libraries
target_link_libraries(CLIController PRIVATE Utilities)