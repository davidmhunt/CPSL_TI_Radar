#ifndef DCA1000_COMMANDS_H
#define DCA1000_COMMANDS_H

#include <cstdint>
#include <cstring>
#include <vector>

class DCA1000Commands {
private:
    static const uint16_t HEADER;
    static const uint16_t FOOTER;

public:
    static const uint16_t RESET_FPGA;
    static const uint16_t RESET_AR_DEV;
    static const uint16_t CONFIG_FPGA_GEN;
    static const uint16_t CONFIG_EEPROM;
    static const uint16_t RECORD_START;
    static const uint16_t RECORD_STOP;
    static const uint16_t PLAYBACK_START;
    static const uint16_t PLAYBACK_STOP;
    static const uint16_t SYSTEM_CONNECT;
    static const uint16_t SYSTEM_ERROR;
    static const uint16_t CONFIG_PACKET_DATA;
    static const uint16_t CONFIG_DATA_MODE_AR_DEV;
    static const uint16_t INIT_FPGA_PLAYBACK;
    static const uint16_t READ_FPGA_VERSION;

    static std::vector<uint8_t> construct_command(
        uint16_t command_code,
        std::vector<uint8_t> data = std::vector<uint8_t>(0));
};


#endif  // DCA1000_COMMANDS_H