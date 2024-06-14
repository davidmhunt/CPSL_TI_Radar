
#check if the json handler is available
find_package(nlohmann_json 3.11.3 QUIET)

#if it isn't download and include it
if (NOT nlohmann_json_FOUND)
    include(FetchContent)
    FetchContent_Declare(json URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz)
    FetchContent_MakeAvailable(json)
endif()

#create the utilities library
add_library(Utilities JSONHandler.cpp)

#link libraries as needed
target_link_libraries(Utilities PUBLIC nlohmann_json::nlohmann_json)

