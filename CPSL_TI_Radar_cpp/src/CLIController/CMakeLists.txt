#declare packages and dependencies
find_package(Threads REQUIRED)
find_package(Boost REQUIRED)

#add libraries
add_library(CLIController CLIController.cpp)

target_include_directories(CLIController PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/CLIController>
)

#link libraries
target_link_libraries(CLIController PUBLIC Utilities
                                    PUBLIC Boost::boost
                                    PUBLIC Threads::Threads)
