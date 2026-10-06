#declare packages and dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(CLIController CLIController.cpp)

target_include_directories(CLIController PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/CLIController>
)

#link libraries
target_link_libraries(CLIController PUBLIC Utilities
                                    PUBLIC Threads::Threads)
