#declare packages and dependencies
find_package(Threads REQUIRED)

#add libraries
#TLVProcessing: the pure frame parser (parse_uart_frame) and the TLV type codes
add_library(TLVProcessing TLVProcessing.cpp UartFrame.cpp)
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
target_link_libraries(TLVProcessing PUBLIC BoardDescriptor PUBLIC Log)
target_link_libraries(SerialStreamer PUBLIC Utilities
                                    PUBLIC Threads::Threads
                                    PUBLIC TLVProcessing)
