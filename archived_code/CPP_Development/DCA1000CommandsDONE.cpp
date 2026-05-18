#include "DCA1000CommandsDONE.hpp"

#include <cstring>

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

void DCA1000Commands::construct_command(uint16_t command_code, const uint8_t* data, uint16_t data_size, uint8_t* command) {
    // add the header (formatted as little-endian)
    uint16_t header = HEADER;
    command[0] = header & 0xFF;
    command[1] = (header >> 8) & 0xFF;

    // add the message code
    command[2] = command_code & 0xFF;
    command[3] = (command_code >> 8) & 0xFF;

    // add the data length
    command[4] = data_size & 0xFF;
    command[5] = (data_size >> 8) & 0xFF;

    // add the data
    if (data != nullptr && data_size > 0) {
        std::memcpy(command + 6, data, data_size);
    }

    // add the footer
    uint16_t footer = FOOTER;
    command[6 + data_size] = footer & 0xFF;
    command[7 + data_size] = (footer >> 8) & 0xFF;
}