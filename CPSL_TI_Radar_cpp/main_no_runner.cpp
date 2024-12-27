//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <csignal>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Commands.hpp"
#include "DCA1000Handler.hpp"

using json = nlohmann::json;

CLIController* cli_global = nullptr;
DCA1000Handler* dca_global = nullptr;

void signalHandler(int signum){
    std::cout << "Interrupt signal (" << signum << ") received.\n";
    if (cli_global && cli_global->initialized) {
        cli_global->sendStopCommand();
    }
    if (dca_global && dca_global->initialized) {
        dca_global->send_recordStop();
    }
}

int main(int, char**){

    //handle sigint commands
    signal(SIGINT,signalHandler);

    std::string config_file = "../configs/radar_0_IWR1843_demo.json";
    
    SystemConfigReader config_reader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getRadarCliPort() << std::endl;
    std::cout << std::endl << "SDK Major Version: " << config_reader.getSDKMajorVersion() << std::endl;
    
    const std::string radar_config_path = config_reader.getRadarConfigPath();
    RadarConfigReader radar_config_reader(radar_config_path);

    // //setup the DCA1000
    // DCA1000Handler dca1000_handler(config_reader,radar_config_reader);
    // dca_global = &dca1000_handler;

    // // //initialize the DCA1000
    // if(dca1000_handler.initialized == false){
    //     return false;
    // }

    // // //send a configuration to the radar board
    // CLIController cli_controller(config_reader);
    // cli_global = &cli_controller;
    // if(cli_controller.initialized){
    //     cli_controller.send_config_to_IWR();
    // }

    // //send record start command
    // dca1000_handler.send_recordStart();

    // //send sensor start command
    // cli_controller.sendStartCommand();

    // //define a buffer
    // for (size_t i = 0; i < 3000; i++)
    // {
    //     dca1000_handler.process_next_packet();
    // }

    // std::cout << "sending IWR stop command" << std::endl;
    // cli_controller.sendStopCommand();

    // std::cout << "sending DCA1000 stop command" << std::endl;
    // dca1000_handler.send_recordStop();
}
