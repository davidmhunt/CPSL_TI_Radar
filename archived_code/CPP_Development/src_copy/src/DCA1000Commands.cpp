#include "DCA1000Commands.hpp"

const uint16_t DCA1000Commands::HEADER = 0xA55A;  // 0xA55A in little endian
const uint16_t DCA1000Commands::FOOTER = 0xEEAA;  // 0xEEAA in little endian

//Removed 0 in front of command codes because of weird Endian stuff
const uint16_t DCA1000Commands::RESET_FPGA = 0x1;
const uint16_t DCA1000Commands::RESET_AR_DEV = 0x2;
const uint16_t DCA1000Commands::CONFIG_FPGA_GEN = 0x3;
const uint16_t DCA1000Commands::CONFIG_EEPROM = 0x4;
const uint16_t DCA1000Commands::RECORD_START = 0x5;
const uint16_t DCA1000Commands::RECORD_STOP = 0x6;
const uint16_t DCA1000Commands::PLAYBACK_START = 0x7;
const uint16_t DCA1000Commands::PLAYBACK_STOP = 0x8;
const uint16_t DCA1000Commands::SYSTEM_CONNECT = 0x9;
const uint16_t DCA1000Commands::SYSTEM_ERROR = 0xA;
const uint16_t DCA1000Commands::CONFIG_PACKET_DATA = 0xB;
const uint16_t DCA1000Commands::CONFIG_DATA_MODE_AR_DEV = 0xC;
const uint16_t DCA1000Commands::INIT_FPGA_PLAYBACK = 0xD;
const uint16_t DCA1000Commands::READ_FPGA_VERSION = 0xE;

/**
 * @brief Construct a command for a given command code
 * 
 * @param command_code The command code to use
 * @param data Any data to be sent as part of the command
 * @return std::vector<uint8_t> 
 */
std::vector<uint8_t> DCA1000Commands::construct_command(
    uint16_t command_code, 
    std::vector<uint8_t> data) {
    
    size_t cmd_len = 8;
    // add the header (formatted as little-endian)
    if (data.size() > 0){
        cmd_len += data.size();
    }
    else{

    }

    //initialize the vectory
    std::vector<uint8_t> command(cmd_len,0);

    //set the header
    uint16_t header = HEADER;
    command[0] = static_cast<uint8_t>(HEADER & 0xFF);
    command[1] = static_cast<uint8_t>((HEADER >> 8) & 0xFF);

    // add the message code
    command[2] = static_cast<uint8_t>(command_code & 0xFF);
    command[3] = static_cast<uint8_t>((command_code >> 8) & 0xFF);

    // add the data length
    command[4] = static_cast<uint8_t>(data.size() & 0xFF);
    command[5] = static_cast<uint8_t>((data.size() >> 8) & 0xFF);

    // add the data
    if (data.size() > 0){
        for (size_t i = 0; i < data.size(); i++)
        {
            command[6+i] = data[i];
        }
        
    }

    // add the footer
    uint16_t footer = FOOTER;
    command[6 + data.size()] = static_cast<uint8_t>(footer & 0xFF);
    command[7 + data.size()] = static_cast<uint8_t>((footer >> 8) & 0xFF);

    return command;
}