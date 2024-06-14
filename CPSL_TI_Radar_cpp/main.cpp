//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "/home/david/CPSL_TI_Radar/CPSL_TI_Radar/json_radar_settings/radar_1.json";

    SystemConfigReader config_reader = SystemConfigReader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
}
