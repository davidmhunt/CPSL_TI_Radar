
#add libraries
add_library(DCA1000Commands  DCA1000Commands.cpp)
add_library(ADCCubeConverter ADCCubeConverter.cpp)
add_library(FrameAssembler   FrameAssembler.cpp)
add_library(DCA1000Socket    DCA1000Socket.cpp)
add_library(DCA1000Handler   DCA1000Handler.cpp)

#link libraries
target_link_libraries(DCA1000Socket     PUBLIC Threads::Threads)

find_package(Threads REQUIRED)

target_link_libraries(DCA1000Handler    PUBLIC Utilities
                                        PUBLIC DCA1000Commands
                                        PUBLIC ADCCubeConverter
                                        PUBLIC FrameAssembler
                                        PUBLIC DCA1000Socket)