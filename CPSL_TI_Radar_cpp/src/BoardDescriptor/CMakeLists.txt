#board and firmware descriptor loaders, radar-cfg cross-checks and cfg command filter
#(design §1); linked by Utilities (SystemConfigReader)
add_library(BoardDescriptor BoardDescriptor.cpp FirmwareDescriptor.cpp)

target_include_directories(BoardDescriptor PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/BoardDescriptor>
)

target_link_libraries(BoardDescriptor PUBLIC nlohmann_json::nlohmann_json)
