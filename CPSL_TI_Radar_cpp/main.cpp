//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Commands.hpp"
#include "DCA1000Handler.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "../configs/radar_1.json";

    SystemConfigReader config_reader = SystemConfigReader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getRadarCliPort() << std::endl;
    
    //setup the DCA1000
    DCA1000Handler dca1000_handler(config_reader);
    
    float fpga_version = dca1000_handler.send_readFPGAVersion();

    std::cout << "FPGA version: " << fpga_version << std::endl;

    //send a configuration to the radar board
    CLIController cli_controller(config_file);
    cli_controller.run();
}
