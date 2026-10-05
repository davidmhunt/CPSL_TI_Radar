find_package(Boost REQUIRED)
find_package(Threads REQUIRED)

#the log sink and Status/Result (Log.hpp, Status.hpp): no dependencies, so the
#hot-path libraries (FrameAssembler, DCA1000Socket) can log without Boost/json
add_library(Log Log.cpp)

#create the utilities library
add_library(Utilities SystemConfigReader.cpp RadarConfigReader.cpp SerialBaud.cpp SerialBaudTermios2.cpp
                      StopSignal.cpp ByteStream.cpp)

foreach(lib Log Utilities)
  target_include_directories(${lib} PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include/${PROJECT_NAME}/utilities>
  )
endforeach()

#link libraries as needed
target_link_libraries(Utilities PUBLIC Log
                                PUBLIC nlohmann_json::nlohmann_json
                                PUBLIC BoardDescriptor
                                PUBLIC Boost::boost
                                PUBLIC Threads::Threads)
