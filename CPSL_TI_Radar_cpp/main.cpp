//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Commands.hpp"
#include "DCA1000Handler.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "../configs/radar_1.json";

    SystemConfigReader config_reader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getRadarCliPort() << std::endl;
    
    const std::string radar_config_path = config_reader.getRadarConfigPath();
    RadarConfigReader radar_config_reader(radar_config_path);

    //setup the DCA1000
    DCA1000Handler dca1000_handler(config_reader,radar_config_reader);

    // //initialize the DCA1000
    if(dca1000_handler.initialized == false){
        return false;
    }

    // //send a configuration to the radar board
    CLIController cli_controller(config_reader);
    if(cli_controller.initialized){
        cli_controller.send_config_to_IWR();
    }

    //send record start command
    dca1000_handler.send_recordStart();

    //send sensor start command
    cli_controller.sendStartCommand();

    //define a buffer
    for (size_t i = 0; i < 3000; i++)
    {
        dca1000_handler.process_next_packet();
    }

    std::cout << "sending IWR stop command" << std::endl;
    cli_controller.sendStopCommand();


    std::cout << "sending DCA1000 stop command" << std::endl;
    dca1000_handler.send_recordStop();
    
}
