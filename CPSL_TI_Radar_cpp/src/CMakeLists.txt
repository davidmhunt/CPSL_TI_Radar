
#add subdirectories
add_subdirectory(utilities) #must be done first
add_subdirectory(CLIController)
add_subdirectory(SerialStreamer)
add_subdirectory(DCA1000)
add_subdirectory(Runners)

#if new libraries are created in this folder, declare them here

#link libraries (if libraries are created in this folder)

#link directories as needed
target_include_directories(CLIController PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/CLIController>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/CLIController>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utilities>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
)

target_include_directories(SerialStreamer PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/SerialStreamer>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/SerialStreamer>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utilities>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
)

target_include_directories(DCA1000Handler PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/DCA1000>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/DCA1000>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utilities>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
)

target_include_directories(DCA1000Runner PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/Runners>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/Runners>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utilities>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/CLIController>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/CLIController>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/SerialStreamer>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/SerialStreamer>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/DCA1000>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/DCA1000>
)

target_include_directories(Runner PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/Runners>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/Runners>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utilities>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/CLIController>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/CLIController>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/SerialStreamer>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/SerialStreamer>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/DCA1000>
  $<INSTALL_INTERFACE:include/${PROJECT_NAME}/DCA1000>
)
