
#create the utilities library
add_library(Utilities JSONHandler.cpp SystemConfigReader.cpp RadarConfigReader.cpp)

#link libraries as needed
target_link_libraries(Utilities PUBLIC nlohmann_json::nlohmann_json)

