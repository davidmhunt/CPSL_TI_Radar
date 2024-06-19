//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "CLIController.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "../configs/radar_1.json";

    SystemConfigReader config_reader = SystemConfigReader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getRadarCliPort() << std::endl;
    //send a configuration to the radar board
    CLIController cli_controller(config_file);
    cli_controller.run();
}
