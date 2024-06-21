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

    //initialize the DCA1000
    if(dca1000_handler.initialize() == false){
        return false;
    }

    //send a configuration to the radar board
    CLIController cli_controller(config_file);
    cli_controller.run();

    //send record start command
    dca1000_handler.send_recordStart();

    //send sensor start command
    cli_controller.sendStartCommand();

    //define a buffer
    std::vector<uint8_t> data_buffer(1472,0);
    while (true)
    {
        dca1000_handler.get_next_udp_packets(data_buffer);
    }
    
}
