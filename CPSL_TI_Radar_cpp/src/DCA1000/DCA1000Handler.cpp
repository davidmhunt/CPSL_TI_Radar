#include "DCA1000Handler.hpp"


DCA1000Handler::DCA1000Handler(const SystemConfigReader& configReader)
    : DCA_fpgaIP(configReader.getDCAFpgaIP()),
      DCA_systemIP(configReader.getDCASystemIP()),
      DCA_cmdPort(configReader.getDCACmdPort()),
      DCA_dataPort(configReader.getDCADataPort()),
      cmd_socket(-1) 
      {
            //setup config address
            cmd_address.sin_family = AF_INET;
            cmd_address.sin_addr.s_addr = inet_addr(DCA_systemIP.c_str());
            cmd_address.sin_port = htons(DCA_cmdPort);

            //setup the data address
            data_address.sin_family = AF_INET;
            data_address.sin_addr.s_addr = inet_addr(DCA_systemIP.c_str());
            data_address.sin_port = htons(DCA_dataPort);
            
            //print key ports
            std::cout << "FPGA IP: " << DCA_fpgaIP << std::endl;
            std::cout << "System IP: " << DCA_systemIP << std::endl;
            std::cout << "cmd port: " << DCA_cmdPort << std::endl;
            std::cout << "data port: " << DCA_dataPort << std::endl;

            //bind to the handler
            init_sockets();
      }

DCA1000Handler::~DCA1000Handler() {
    if (cmd_socket >= 0) {
        close(cmd_socket);
    }
}

bool DCA1000Handler::init_sockets() {

    // Create socket
    cmd_socket = socket(AF_INET, SOCK_DGRAM, 0);
    if (cmd_socket < 0) {
        std::cerr << "Failed to create socket" << std::endl;
        return false;
    }

    // Set socket timeout
    struct timeval timeout;
    timeout.tv_sec = 1;
    timeout.tv_usec = 0;
    setsockopt(cmd_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    //bind to command socket
    if (bind(cmd_socket, (struct sockaddr*)&cmd_address, sizeof(cmd_address)) < 0) {
        std::cerr << "Failed to bind socket" << std::endl;
        close(cmd_socket);
        cmd_socket = -1;
        return false;
    } else{
        std::cout << "Bound to command socket" <<std::endl;
    }

    return true;
}


bool DCA1000Handler::sendCommand(std::vector<uint8_t>& command) {
    if (cmd_socket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    //define address to send to
    struct sockaddr_in fpgaAddr;
    fpgaAddr.sin_family = AF_INET;
    fpgaAddr.sin_addr.s_addr = inet_addr(DCA_fpgaIP.c_str());
    fpgaAddr.sin_port = htons(DCA_cmdPort);

    ssize_t sentBytes = sendto(cmd_socket, command.data(), command.size(), 0,
                               (struct sockaddr*)&fpgaAddr, sizeof(fpgaAddr));
    if (sentBytes != static_cast<ssize_t>(command.size())) {
        std::cerr << "Failed to send command" << std::endl;
        return false;
    }

    return true;
}

bool DCA1000Handler::receiveResponse(std::vector<uint8_t>& buffer) {
    if (cmd_socket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    struct sockaddr_in fromAddr;
    socklen_t fromLen = sizeof(fromAddr);
    ssize_t receivedBytes = recvfrom(cmd_socket, buffer.data(), buffer.size(), 0,
                             (struct sockaddr*)&fromAddr, &fromLen);
    if (receivedBytes < 0) {
        std::cerr << "Failed to receive data" << std::endl;
        return false;
    }

    return true;
}

float DCA1000Handler::send_readFPGAVersion(){

    //get the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                    DCA1000Commands::READ_FPGA_VERSION);

    //send the command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){
        
        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //get version numbers
        uint16_t major_version = (status & 0b01111111);
        uint16_t minor_version = (status >> 7) & 0b01111111;

        return static_cast<float>(major_version) + (static_cast<float>(minor_version)*1e-1);
    }else{
        return 0.0;
    }

}