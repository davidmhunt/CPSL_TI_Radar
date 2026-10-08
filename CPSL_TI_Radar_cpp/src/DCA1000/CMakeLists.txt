#declare packages and dependencies
find_package(Threads REQUIRED)

#add libraries
add_library(DCA1000Commands  DCA1000Commands.cpp)
add_library(ADCCubeConverter ADCCubeConverter.cpp)
add_library(FrameAssembler   FrameAssembler.cpp)
add_library(DCA1000Socket    DCA1000Socket.cpp)
add_library(PacketSource     PacketSource.cpp)
add_library(SarMeta          SarMeta.cpp)
add_library(DCA1000Handler   DCA1000Handler.cpp)

#every DCA1000 library exposes the shared DCA1000 header directory
foreach(lib DCA1000Commands ADCCubeConverter FrameAssembler DCA1000Socket PacketSource SarMeta DCA1000Handler)
  target_include_directories(${lib} PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include/${PROJECT_NAME}/DCA1000>
  )
endforeach()

#link libraries
target_link_libraries(ADCCubeConverter  PUBLIC BoardDescriptor)  #LvdsLayout / IqOrder
target_link_libraries(FrameAssembler    PUBLIC Log)
target_link_libraries(DCA1000Socket     PUBLIC Log
                                        PUBLIC Threads::Threads)

target_link_libraries(PacketSource      PUBLIC Utilities
                                        PUBLIC DCA1000Commands
                                        PUBLIC DCA1000Socket)

target_link_libraries(DCA1000Handler    PUBLIC Utilities
                                        PUBLIC ADCCubeConverter
                                        PUBLIC FrameAssembler
                                        PUBLIC PacketSource
                                        PUBLIC SarMeta)
