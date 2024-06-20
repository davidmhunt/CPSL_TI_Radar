#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <iostream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <vector>

#include "SystemConfigReader.hpp"
#include "DCA1000Commands.hpp"


class DCA1000Handler {
public:
    DCA1000Handler(const SystemConfigReader& configReader);
    ~DCA1000Handler();

    bool init_sockets();
    bool sendCommand(std::vector<uint8_t>& command);
    bool receiveResponse(std::vector<uint8_t>& buffer);

    //commands to the DCA1000
    bool send_resetFPGA();
    bool send_recordStart();
    bool send_recordStop();
    bool send_systemConnect();
    bool send_packetDataCmd();
    bool send_initFPGAPlayback();
    float send_readFPGAVersion();

private:
    std::string DCA_fpgaIP;
    std::string DCA_systemIP;
    int DCA_cmdPort;
    int DCA_dataPort;

    //command and data sockets
    int cmd_socket;

    //addresses
    sockaddr_in cmd_address;
    sockaddr_in data_address;
};

#endif // DCA1000_H