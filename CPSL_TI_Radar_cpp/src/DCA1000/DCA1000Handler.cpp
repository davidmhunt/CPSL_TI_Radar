#include "DCA1000Handler.hpp"

/**
 * @brief Construct a new DCA1000Handler::DCA1000Handler object
 * 
 * @param configReader 
 */
DCA1000Handler::DCA1000Handler(const SystemConfigReader& configReader)
    : DCA_fpgaIP(configReader.getDCAFpgaIP()),
      DCA_systemIP(configReader.getDCASystemIP()),
      DCA_cmdPort(configReader.getDCACmdPort()),
      DCA_dataPort(configReader.getDCADataPort()),
      cmd_socket(-1) ,
      data_socket(-1)
      {     
            //print key ports
            std::cout << "FPGA IP: " << DCA_fpgaIP << std::endl;
            std::cout << "System IP: " << DCA_systemIP << std::endl;
            std::cout << "cmd port: " << DCA_cmdPort << std::endl;
            std::cout << "data port: " << DCA_dataPort << std::endl;
      }

/**
 * @brief Destroy the DCA1000Handler::DCA1000Handler object
 * 
 */
DCA1000Handler::~DCA1000Handler() {
    if (cmd_socket >= 0) {
        send_recordStop();
        close(cmd_socket);
    }
    if (data_socket >= 0){
        close(data_socket);
    }
}

bool DCA1000Handler::initialize(){

    //initialize the addresses
    init_addresses();

    //initialize sockets
    if(init_sockets() != true){
        return false;
    }

    //send system connect
    if(send_systemConnect() != true){
        return false;
    }

    //send reset FPGA
    if(send_resetFPGA() != true){
        return false;
    }

    //send configure packet data
    if(send_configPacketData(1472,25) != true){
        return false;
    }

    //send config FPGA gen
    if(send_configFPGAGen() != true){
        return false;
    }

    //read the FPGA version
    float fpga_version = send_readFPGAVersion();

    if(fpga_version > 0){
        std::cout << "FPGA (firmware version: " << fpga_version << ") initialized successfully";
        return true;
    } else{
        return false;
    }
}

/**
 * @brief Setup the command and data addresses
 * 
 */
void DCA1000Handler::init_addresses() {
    //setup config address
    cmd_address.sin_family = AF_INET;
    cmd_address.sin_addr.s_addr = inet_addr(DCA_systemIP.c_str());
    cmd_address.sin_port = htons(DCA_cmdPort);

    //setup the data address
    data_address.sin_family = AF_INET;
    data_address.sin_addr.s_addr = inet_addr(DCA_systemIP.c_str());
    data_address.sin_port = htons(DCA_dataPort);
}

/**
 * @brief 
 * 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::init_sockets() {

    // Create socket
    cmd_socket = socket(AF_INET, SOCK_DGRAM, 0);
    if (cmd_socket < 0) {
        std::cerr << "Failed to create cmd socket" << std::endl;
        return false;
    }

    data_socket = socket(AF_INET, SOCK_DGRAM, 0);
    if (data_socket < 0) {
        std::cerr << "Failed to create data socket" << std::endl;
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

    //bind to data socket
    if (bind(data_socket, (struct sockaddr*)&data_address, sizeof(data_address)) < 0) {
        std::cerr << "Failed to bind socket" << std::endl;
        close(data_socket);
        data_socket = -1;
        return false;
    } else{
        std::cout << "Bound to data socket" <<std::endl;
    }

    return true;
}

/**
 * @brief 
 * 
 * @param command 
 * @return true 
 * @return false 
 */
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

/**
 * @brief 
 * 
 * @param buffer 
 * @return true 
 * @return false 
 */
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

/**
 * @brief 
 * 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::send_resetFPGA(){

    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::RESET_FPGA);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else{
        return false;
    }
}

bool DCA1000Handler::send_recordStart(){
    
    //get the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::RECORD_START);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else{
        return false;
    }
}

bool DCA1000Handler::send_recordStop(){
    
    //get the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::RECORD_STOP);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else{
        return false;
    }
}

bool DCA1000Handler::send_systemConnect(){
    
    //get the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::SYSTEM_CONNECT);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else{
        return false;
    }
}

/**
 * @brief 
 * 
 * @param packet_size 
 * @param delay_us 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::send_configPacketData(uint16_t packet_size, uint16_t delay_us){

    //declare data vector
    std::vector<uint8_t> data(6,0);

    //define packet size
    data[0] = static_cast<uint8_t>(packet_size & 0xFF);
    data[1] = static_cast<uint8_t>((packet_size >> 8) & 0xFF);

    //define delay
    data[2] = static_cast<uint8_t>(delay_us & 0xFF);
    data[3] = static_cast<uint8_t>((delay_us >> 8) & 0xFF);

    // bytes 4 & 5 are future use

    //generate the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::CONFIG_PACKET_DATA,
                                        data);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else {
        return false;
    }
}

bool DCA1000Handler::send_configFPGAGen(){
    std::vector<uint8_t> data(6,0);

    //data logging mode - Raw Mode
    data[0] = 0x01;

    //LVDS mode - 4 lane
    data[1] = 0x01;

    //data transfer mode - LVDS capture
    data[2] = 0x01;

    //data capture mode
    data[3] = 0x02;

    //data format mode
    data[4] = 0x03;

    //timer - default to 30 seconds
    data[5] = 30;

    //generate the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::CONFIG_FPGA_GEN,
                                        data);
    
    //send command
    sendCommand(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (receiveResponse(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            return true;
        }else{
            return false;
        }
    } else {
        return false;
    }
}

/**
 * @brief 
 * 
 * @return float 
 */
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

/**
 * @brief 
 * 
 * @param buffer 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::get_next_udp_packets(std::vector<uint8_t>& buffer) {
    if (data_socket < 0) {
        std::cerr << "data socket not bound" << std::endl;
        return false;
    }

    struct sockaddr_in fromAddr;
    socklen_t fromLen = sizeof(fromAddr);
    ssize_t receivedBytes = recvfrom(data_socket, buffer.data(), buffer.size(), 0,
                             (struct sockaddr*)&fromAddr, &fromLen);
    if (receivedBytes < 0) {
        std::cerr << "Failed to receive data" << std::endl;
        return false;
    } else{
        std::cout << "p";
    }

    return true;
}