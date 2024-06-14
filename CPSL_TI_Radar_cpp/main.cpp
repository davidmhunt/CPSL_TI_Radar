//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>

//JSON handling
#include "JSONHandler.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "/home/david/CPSL_TI_Radar/CPSL_TI_Radar/json_radar_settings/radar_1.json";

    json json_config = JSONHandler::parse_JSON(config_file,false);
    std::string config_path = json_config["TI_Radar_Config_Management"]["TI_Radar_config_path"].get<std::string>();
    std::cout << "Config file: " << config_path;
}
