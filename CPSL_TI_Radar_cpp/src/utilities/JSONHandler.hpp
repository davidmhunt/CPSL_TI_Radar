#ifndef JSONHANDLER
#define JSONHANDLER

//Inlcude files in the C standard library
#include <iostream>
#include <cstdlib>
#include <fstream>
#include <string>

//include extra files
#include "nlohmann/json.hpp"

using json = nlohmann::json;

namespace JSONHandler {
    json parse_JSON(std::string & file_name, bool print_JSON = false);
    void print_file(std::string & file_name);
}


#endif