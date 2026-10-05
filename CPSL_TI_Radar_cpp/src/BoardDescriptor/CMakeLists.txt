#board descriptor loader and radar-cfg cross-checks (design §1); not linked
#into the driver yet (core-10 wires it in)
add_library(BoardDescriptor BoardDescriptor.cpp)

target_include_directories(BoardDescriptor PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/BoardDescriptor>
)

target_link_libraries(BoardDescriptor PUBLIC nlohmann_json::nlohmann_json)
