#declare packages and dependencies
find_package(Threads REQUIRED)
find_package(Boost REQUIRED)

#add libraries
add_library(TLVProcessing TLVProcessing.cpp)
add_library(SerialStreamer SerialStreamer.cpp)

target_include_directories(TLVProcessing PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/SerialStreamer>
)
target_include_directories(SerialStreamer PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/SerialStreamer>
)

#link libraries
target_link_libraries(SerialStreamer PUBLIC Utilities
                                    PUBLIC Boost::boost
                                    PUBLIC Threads::Threads
                                    PUBLIC TLVProcessing)
