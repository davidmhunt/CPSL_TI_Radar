//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <fstream>
#include <iostream>

//JSON handling
#include "RadarConfigReaderDONE.hpp"
//#include "IWRConfig.hpp"
#include "DCA1000CommandsDONE.hpp"
#include "DCA1000HandlerDONE.hpp"
#include "json.hpp"

using json = nlohmann::json;


int main(int, char**){

    std::string config_file = "/home/cpsl/Documents/CPSL_TI_Radar/CPSL_TI_Radar_cpp/configs/radar_1.json";

    RadarConfigReader config_reader = RadarConfigReader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getCliPort() << std::endl;
/*
    //construct read_FPGA command
    const uint16_t HEADER = 0xA55A;  // 0xA55A in little endian
    const uint16_t FOOTER = 0xEEAA;  // 0xEEAA in little endian
    const uint16_t command_code = 0xE;
    
    std::vector<uint8_t> command(8,0);
    //set the header
    uint16_t header = HEADER;
    command[0] = static_cast<uint8_t>(HEADER & 0xFF);
    command[1] = static_cast<uint8_t>((HEADER >> 8) & 0xFF);

    // add the message code
    command[2] = static_cast<uint8_t>(command_code & 0xFF);
    command[3] = static_cast<uint8_t>((command_code >> 8) & 0xFF);

    // add the data length
    command[4] = static_cast<uint8_t>(0 & 0xFF);
    command[5] = static_cast<uint8_t>((0 >> 8) & 0xFF);
    
    // add the footer
    uint16_t footer = FOOTER;
    command[6] = static_cast<uint8_t>(footer & 0xFF);
    command[7] = static_cast<uint8_t>((footer >> 8) & 0xFF);

*/  
    const uint8_t command = 0xA55AE0000000FFFF;
    const uint8_t* command_ptr = &command;
    
    //setup the DCA1000
    DCA1000 dca1000_handler(config_reader);

    bool bound = dca1000_handler.bind();
    
    bool fpga_version = dca1000_handler.sendCommand(command_ptr, 8);

    std::cout << "FPGA version: " << fpga_version << std::endl;

    //send a configuration to the radar board
  //  CLIController cli_controller(config_file);
   // cli_controller.run();
}
