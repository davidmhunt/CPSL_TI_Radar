#include "DCA1000Handler.hpp"

/**
 * @brief Default constructor (un-initialized)
 */
DCA1000Handler::DCA1000Handler():
    initialized(false),
    new_frame_available(false),
    new_frame_available_mutex(),
    adc_data_cube_mutex(),
    system_config_reader(),
    radar_config_reader(),
    DCA_fpgaIP(""),
    DCA_systemIP(""),
    DCA_cmdPort(-1),
    DCA_dataPort(-1),
    cmd_socket(new int(-1)),
    data_socket(new int(-1)),
    cmd_address(),
    data_address(),
    udp_packet_buffer(),
    udp_packet_size(1472),
    dropped_packets(0),
    dropped_packet_events(0),
    received_packets(0),
    adc_data_byte_count(0),
    frame_byte_buffer(),
    received_frames(0),
    next_frame_byte_buffer_idx(0),
    bytes_per_frame(0),
    samples_per_chirp(0),
    chirps_per_frame(0),
    num_rx_channels(4),
    save_to_file(false),
    adc_cube_out_file(nullptr),
    raw_lvds_out_file(nullptr),
    adc_data_cube(),
    latest_frame_byte_buffer()
{}

/**
 * @brief Constructor (initializes handler)
 * 
 * @param configReader 
 */
DCA1000Handler::DCA1000Handler( const SystemConfigReader& configReader,
                                const RadarConfigReader& radarConfigReader):
    initialized(false),
    new_frame_available(false),
    new_frame_available_mutex(),
    adc_data_cube_mutex(),
    system_config_reader(),
    radar_config_reader(),
    DCA_fpgaIP(""),
    DCA_systemIP(""),
    DCA_cmdPort(-1),
    DCA_dataPort(-1),
    cmd_socket(new int(-1)),
    data_socket(new int(-1)),
    cmd_address(),
    data_address(),
    udp_packet_buffer(),
    udp_packet_size(1472),
    dropped_packets(0),
    dropped_packet_events(0),
    received_packets(0),
    adc_data_byte_count(0),
    frame_byte_buffer(),
    received_frames(0),
    next_frame_byte_buffer_idx(0),
    bytes_per_frame(0),
    samples_per_chirp(0),
    chirps_per_frame(0),
    num_rx_channels(4),
    save_to_file(false),
    adc_cube_out_file(nullptr),
    raw_lvds_out_file(nullptr),
    adc_data_cube(),
    latest_frame_byte_buffer()
    {     
        initialize(configReader,radarConfigReader);
    }
/**
 * @brief Copy constructor
 * 
 * @param rhs 
 */
DCA1000Handler::DCA1000Handler(const DCA1000Handler & rhs):
    initialized(rhs.initialized),
    new_frame_available(rhs.new_frame_available),
    new_frame_available_mutex(), //mutexes aren't copyable
    adc_data_cube_mutex(), //mutexes aren't copyable
    system_config_reader(rhs.system_config_reader),
    radar_config_reader(rhs.radar_config_reader),
    DCA_fpgaIP(rhs.DCA_fpgaIP),
    DCA_systemIP(rhs.DCA_systemIP),
    DCA_cmdPort(rhs.DCA_cmdPort),
    DCA_dataPort(rhs.DCA_dataPort),
    cmd_socket(rhs.cmd_socket),
    data_socket(rhs.data_socket),
    cmd_address(rhs.cmd_address),
    data_address(rhs.data_address),
    udp_packet_buffer(rhs.udp_packet_buffer),
    udp_packet_size(rhs.udp_packet_size),
    dropped_packets(rhs.dropped_packets),
    dropped_packet_events(rhs.dropped_packet_events),
    received_packets(rhs.received_packets),
    adc_data_byte_count(rhs.adc_data_byte_count),
    frame_byte_buffer(rhs.frame_byte_buffer),
    received_frames(rhs.received_frames),
    next_frame_byte_buffer_idx(rhs.next_frame_byte_buffer_idx),
    bytes_per_frame(rhs.bytes_per_frame),
    samples_per_chirp(rhs.samples_per_chirp),
    chirps_per_frame(rhs.chirps_per_frame),
    num_rx_channels(rhs.num_rx_channels),
    save_to_file(rhs.save_to_file),
    adc_cube_out_file(rhs.adc_cube_out_file),
    raw_lvds_out_file(rhs.raw_lvds_out_file),
    adc_data_cube(rhs.adc_data_cube),
    latest_frame_byte_buffer(rhs.latest_frame_byte_buffer)
{}

DCA1000Handler & DCA1000Handler::operator=(const DCA1000Handler & rhs){
    if(this != &rhs){

        //check the sockets
        int error_code;
        socklen_t error_code_size = sizeof(error_code);

        //check the command socket isn't bound currently
        if (cmd_socket.get() != nullptr &&
            cmd_socket.use_count() == 1 &&
            *cmd_socket != -1){

            //check to see if the socket is connected or bound
            getsockopt(*cmd_socket,SOL_SOCKET,SO_ERROR,&error_code, &error_code_size);
            if(error_code == 0){
                close(*cmd_socket);
            }
        }

        //check the data socket
        if (data_socket.get() != nullptr &&
            data_socket.use_count() == 1 &&
            *data_socket != -1){

            //check to see if the socket is connected/bound
            getsockopt(*data_socket,SOL_SOCKET,SO_ERROR,&error_code, &error_code_size);
            if(error_code == 0){
                close(*data_socket);
            }
        }

        //close the file streaming
        if (save_to_file)
        {
            if (adc_cube_out_file.get() != nullptr &&
                adc_cube_out_file.use_count() == 1 &&
                adc_cube_out_file -> is_open())
            {
                adc_cube_out_file -> close();
            }
            if (raw_lvds_out_file.get() != nullptr &&
                raw_lvds_out_file.use_count() == 1 &&
                raw_lvds_out_file -> is_open())
            {
                raw_lvds_out_file -> close();
            }
        }


        //assign the variables as normal now
        initialized = rhs.initialized;
        new_frame_available = rhs.new_frame_available;
        //don't re-assign the mutex operators
        system_config_reader = rhs.system_config_reader;
        radar_config_reader = rhs.radar_config_reader;
        DCA_fpgaIP = rhs.DCA_fpgaIP;
        DCA_systemIP = rhs.DCA_systemIP;
        DCA_cmdPort = rhs.DCA_cmdPort;
        DCA_dataPort = rhs.DCA_dataPort;
        cmd_socket = rhs.cmd_socket;
        data_socket = rhs.data_socket;
        cmd_address = rhs.cmd_address;
        data_address = rhs.data_address;
        udp_packet_buffer = rhs.udp_packet_buffer;
        udp_packet_size = rhs.udp_packet_size;
        dropped_packets = rhs.dropped_packets;
        dropped_packet_events = rhs.dropped_packet_events;
        received_packets = rhs.received_packets;
        adc_data_byte_count = rhs.adc_data_byte_count;
        frame_byte_buffer = rhs.frame_byte_buffer;
        received_frames = rhs.received_frames;
        next_frame_byte_buffer_idx = rhs.next_frame_byte_buffer_idx;
        bytes_per_frame = rhs.bytes_per_frame;
        samples_per_chirp = rhs.samples_per_chirp;
        chirps_per_frame = rhs.chirps_per_frame;
        num_rx_channels = rhs.num_rx_channels;
        save_to_file = rhs.save_to_file;
        adc_cube_out_file = rhs.adc_cube_out_file;
        raw_lvds_out_file = rhs.raw_lvds_out_file;
        adc_data_cube = rhs.adc_data_cube;
        latest_frame_byte_buffer = rhs.latest_frame_byte_buffer;
    }

    return *this;
}

/**
 * @brief Destroy the DCA1000Handler::DCA1000Handler object
 * 
 */
DCA1000Handler::~DCA1000Handler() {

    int error_code;
    socklen_t error_code_size = sizeof(error_code);

    //check the command socket
    if (cmd_socket.get() != nullptr &&
        cmd_socket.use_count() == 1 &&
        *cmd_socket != -1){

        //check to see if the socket is connected or bound
        getsockopt(*cmd_socket,SOL_SOCKET,SO_ERROR,&error_code, &error_code_size);
        if(error_code == 0){
            close(*cmd_socket);
        }
    }

    //check the data socket
    if (data_socket.get() != nullptr &&
        data_socket.use_count() == 1 &&
        *data_socket != -1){

        //check to see if the socket is connected/bound
        getsockopt(*data_socket,SOL_SOCKET,SO_ERROR,&error_code, &error_code_size);
        if(error_code == 0){
            close(*data_socket);
        }
    }

    //close the file streaming
        if (save_to_file)
        {
            if (adc_cube_out_file.get() != nullptr &&
                adc_cube_out_file.use_count() == 1 &&
                adc_cube_out_file -> is_open())
            {
                adc_cube_out_file -> close();
            }
            if (raw_lvds_out_file.get() != nullptr &&
                raw_lvds_out_file.use_count() == 1 &&
                raw_lvds_out_file -> is_open())
            {
                raw_lvds_out_file -> close();
            }
        }
}

bool DCA1000Handler::initialize(
    const SystemConfigReader& systemConfigReader,
    const RadarConfigReader& radarConfigReader){

    initialized = false;

    //load the system configuration information
    system_config_reader = systemConfigReader;
    if(system_config_reader.initialized == false){
        return false;
    } else{
        load_config();
    }

    //initialize file streaming
    if(save_to_file){
        if(init_out_file() != true){
            return false;
        }
    }

    //initialize the addresses
    init_addresses();

    //initialize sockets
    if(init_sockets() != true){
        return false;
    }

    //configure the DCA1000
    if(configure_DCA1000() != true){
        initialized = false; //initializing the DCA1000 falied
        return false;
    }

    //load the radar config reader
    radar_config_reader = radarConfigReader;
    if(radar_config_reader.initialized == false){
        return false;
    }else{
        init_buffers();
    }

    //set initialization status to true
    initialized = true;
    
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
bool DCA1000Handler::send_configPacketData(size_t packet_size, uint16_t delay_us){

    //declare data vector
    std::vector<uint8_t> data(6,0);

    //define packet size
    std::uint16_t pkt_size = static_cast<std::uint16_t>(packet_size);
    data[0] = static_cast<uint8_t>(pkt_size & 0xFF);
    data[1] = static_cast<uint8_t>((pkt_size >> 8) & 0xFF);

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

/**
 * @brief Send the Configure FPGA Command
 * 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::send_configFPGAGen(){
    std::vector<uint8_t> data(6,0);

    //data logging mode - Raw Mode
    data[0] = 0x01;

    //LVDS mode - 4 lane (sdk 2.1/IWR1443)
    if (system_config_reader.getSDKMajorVersion() == 2){
        data[1] = 0x01;
    } 
    // 2 lane (sdk 3+/IWR6843,IWR1843)
    else if (system_config_reader.getSDKMajorVersion() == 3)
    {
        data[1] = 0x02;
    }
    else{
        std::cerr << "DCA1000Handler::send_config_FPGAGen(): invalid SDK major version" << std::endl;
        return false;
    }

    //data transfer mode - LVDS capture
    data[2] = 0x01;

    //data capture mode - ethernet stream
    data[3] = 0x02;

    //data format mode - 16 bit
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
 * @return true 
 * @return false 
 */
bool DCA1000Handler::process_next_packet(){

    ssize_t received_bytes = get_next_udp_packets(udp_packet_buffer);
    if(received_bytes > 0){

        //get the sequence number
        std::uint32_t packet_sequence_number = get_packet_sequence_number(udp_packet_buffer);

        //determine bytes in the new packet
        std::uint64_t packet_byte_count = get_packet_byte_count(udp_packet_buffer);
        std::uint64_t adc_data_bytes_in_packet = static_cast<std::uint64_t>(received_bytes) - 10;
        
        //check for and handle dropped packets
        if (packet_sequence_number != received_packets + 1){
            std::cout << "d-P: " << packet_sequence_number << std::endl;

            //determine the number of dropped packets
            dropped_packets += (packet_sequence_number - received_packets + 1);
            dropped_packet_events += 1;

            zero_pad_frame_byte_buffer(packet_byte_count);

            //update the received packet total
            received_packets = packet_sequence_number;
        } else{
            received_packets += 1;
        }

        //check to make sure all bytes are accounted for
        if (adc_data_byte_count != packet_byte_count){
            std::cout << "d-B" << std::endl;
            
            zero_pad_frame_byte_buffer(packet_byte_count);

        } else{
            adc_data_byte_count += adc_data_bytes_in_packet;
        }

        //copy the bytes into the frame byte buffer
        for (size_t i = 0; i < adc_data_bytes_in_packet; i++)
        {
            frame_byte_buffer[next_frame_byte_buffer_idx] = udp_packet_buffer[i + 10];
            
            //increment the frame byte buffer index
            next_frame_byte_buffer_idx += 1;
            if(next_frame_byte_buffer_idx == bytes_per_frame){

                //save the completed frame byte buffer and reset it
                save_frame_byte_buffer();
            }

            //save the raw data if desired
            if(save_to_file)
            {
                raw_lvds_out_file -> write(
                        reinterpret_cast<const char*>(
                            &udp_packet_buffer[i+10]),
                        sizeof(udp_packet_buffer[i+10])
                    );
            }
        }
        return true;
    } else{
        return false;
    }
}

/**
 * @brief Determine if a new frame's adc data cube is now available in a thread safe manner
 * 
 * @return true - a new frame is available
 * @return false - a new frame is not available
 */
bool DCA1000Handler::check_new_frame_available(){

    std::unique_lock<std::mutex> new_frame_available_unique_lock(
        new_frame_available_mutex,
        std::defer_lock
    );
    bool status;

    //get the status in a thread safe way
    new_frame_available_unique_lock.lock();
    status = new_frame_available;
    new_frame_available_unique_lock.unlock();

    return status;
}

/**
 * @brief Get the latest adc data cube and set the new_frame_available variable to false
 * 
 * @return std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> 
 */
std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> DCA1000Handler::get_latest_adc_cube()
{

    std::unique_lock<std::mutex> adc_data_cube_unique_lock(
        adc_data_cube_mutex,
        std::defer_lock
    );
    std::unique_lock<std::mutex> new_frame_available_unique_lock(
        new_frame_available_mutex,
        std::defer_lock
    );

    //get the latest adc data cube in a thread safe manner
    adc_data_cube_unique_lock.lock();
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> latest_cube = adc_data_cube;
    adc_data_cube_unique_lock.unlock();

    //reset the new_frame_available flage
    new_frame_available_unique_lock.lock();
    new_frame_available = false;
    new_frame_available_unique_lock.unlock();

    return latest_cube;

}

/**
 * @brief Load required information from the system_config_reader
 * 
 */
void DCA1000Handler::load_config(){

    DCA_fpgaIP = system_config_reader.getDCAFpgaIP();
    DCA_systemIP = system_config_reader.getDCASystemIP();
    DCA_cmdPort = system_config_reader.getDCACmdPort();
    DCA_dataPort = system_config_reader.getDCADataPort();
    save_to_file = system_config_reader.get_save_to_file();

    //print key ports
    std::cout << "FPGA IP: " << DCA_fpgaIP << std::endl;
    std::cout << "System IP: " << DCA_systemIP << std::endl;
    std::cout << "cmd port: " << DCA_cmdPort << std::endl;
    std::cout << "data port: " << DCA_dataPort << std::endl;
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
    cmd_socket = std::make_shared<int>(socket(AF_INET, SOCK_DGRAM, 0));
    if (*cmd_socket < 0) {
        std::cerr << "Failed to create cmd socket" << std::endl;
        return false;
    }

    data_socket = std::make_shared<int>(socket(AF_INET, SOCK_DGRAM, 0));
    if (*data_socket < 0) {
        std::cerr << "Failed to create data socket" << std::endl;
        return false;
    }

    // Set socket timeout
    struct timeval timeout;
    timeout.tv_sec = 2;
    timeout.tv_usec = 0;
    setsockopt(*cmd_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(*data_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    //bind to command socket
    if (bind(*cmd_socket, (struct sockaddr*)&cmd_address, sizeof(cmd_address)) < 0) {
        std::cerr << "Failed to bind to cmd socket" << std::endl;
        close(*cmd_socket);
        *cmd_socket = -1;
        return false;
    } else{
        std::cout << "Bound to command socket" <<std::endl;
    }

    //bind to data socket
    if (bind(*data_socket, (struct sockaddr*)&data_address, sizeof(data_address)) < 0) {
        std::cerr << "Failed to bind to data socket" << std::endl;
        close(*data_socket);
        *data_socket = -1;
        return false;
    } else{
        std::cout << "Bound to data socket" <<std::endl;
    }
    return true;
}

/**
 * @brief Send a series of commands to the DCA1000 to configure it
 * 
 * @return true - DCA1000 successfully configured
 * @return false - DCA1000 not successfully configured
 */
bool DCA1000Handler::configure_DCA1000(){

    //check that the command socket is all good
    int error_code;
    socklen_t error_code_size = sizeof(error_code);

    //check the command socket
    if (cmd_socket.get() != nullptr &&
        *cmd_socket != -1){

        //check to see if the socket is connected or bound
        getsockopt(*cmd_socket,SOL_SOCKET,SO_ERROR,&error_code, &error_code_size);
        if(error_code != 0){
            std::cerr << "attempted to configure DCA1000,\
                        but cmd_socket isn't connected/bound" << std::endl;
            return false;   
        }
    }else{
        std::cerr << "attempted to configure DCA1000,\
                    but cmd_socket is either null pointer\
                    or not connected" << std::endl;
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
    udp_packet_size = 1472;
    if(send_configPacketData(udp_packet_size,25) != true){
        return false;
    }

    //send config FPGA gen
    if(send_configFPGAGen() != true){
        return false;
    }

    //read the FPGA version
    float fpga_version = send_readFPGAVersion();

    if(fpga_version > 0){
        std::cout << "FPGA (firmware version: " << fpga_version << ") initialized successfully" << std::endl;
        return true;
    } else{
        return false;
    }
}

/**
 * @brief 
 * 
 * @param command 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::sendCommand(std::vector<uint8_t>& command) {
    if (*cmd_socket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    //define address to send to
    struct sockaddr_in fpgaAddr;
    fpgaAddr.sin_family = AF_INET;
    fpgaAddr.sin_addr.s_addr = inet_addr(DCA_fpgaIP.c_str());
    fpgaAddr.sin_port = htons(DCA_cmdPort);

    ssize_t sentBytes = sendto(*cmd_socket, command.data(), command.size(), 0,
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
    if (*cmd_socket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    struct sockaddr_in fromAddr;
    socklen_t fromLen = sizeof(fromAddr);
    ssize_t receivedBytes = recvfrom(*cmd_socket, buffer.data(), buffer.size(), 0,
                             (struct sockaddr*)&fromAddr, &fromLen);
    if (receivedBytes < 0) {
        std::cerr << "Failed to receive data" << std::endl;
        return false;
    }

    return true;
}

void DCA1000Handler::init_buffers()
{
    if(radar_config_reader.initialized){
        bytes_per_frame = radar_config_reader.get_bytes_per_frame();
        samples_per_chirp = radar_config_reader.get_samples_per_chirp();
        chirps_per_frame = radar_config_reader.get_chirps_per_frame();
        num_rx_channels = radar_config_reader.get_num_rx_antennas();

        //configure the udp packet buffer
        udp_packet_buffer = std::vector<uint8_t>(udp_packet_size,0);

        //configure the frame byte buffer (assembly)
        frame_byte_buffer = std::vector<uint8_t>(bytes_per_frame,0);
        next_frame_byte_buffer_idx = 0;

        //configure processing of completed frames
        latest_frame_byte_buffer = std::vector<uint8_t>(bytes_per_frame,0);
        new_frame_available = false;

        //reset the dropped packet counting
        received_packets = 0;
        adc_data_byte_count = 0;
        dropped_packets = 0;
        received_frames = 0;

        //adc_cube buffer
        //NOTE: indexed by [Rx channel, sample, chirp]
        adc_data_cube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>(
            num_rx_channels,std::vector<std::vector<std::complex<std::int16_t>>>(
                samples_per_chirp, std::vector<std::complex<std::int16_t>>(
                    chirps_per_frame,std::complex<std::int16_t>(0,0)
                )
            )
        );
    }else{
        std::cerr << "attempted to initialize DCA1000 Handler buffers,\
        but radar_config_reader wasn't initialized";
    }
}

/**
 * @brief 
 * 
 * @param buffer 
 * @return true 
 * @return false 
 */
ssize_t DCA1000Handler::get_next_udp_packets(std::vector<uint8_t>& buffer) {
    if (*data_socket < 0) {
        std::cerr << "data socket not bound" << std::endl;
        return 0;
    }

    struct sockaddr_in fromAddr;
    socklen_t fromLen = sizeof(fromAddr);
    ssize_t receivedBytes = recvfrom(*data_socket, buffer.data(), buffer.size(), 0,
                             (struct sockaddr*)&fromAddr, &fromLen);
    if (receivedBytes < 0) {
        std::cerr << "Failed to receive data" << std::endl;
        return 0;
    } else{
        return receivedBytes;
    }
}

void DCA1000Handler::print_status(){
    if(system_config_reader.get_verbose()){
        std::cout <<
        "frame: " << received_frames << std::endl <<
        "\tpackets: " << received_packets << std::endl <<
        "\tdata bytes: " << adc_data_byte_count << std::endl <<
        "\tdropped packets: " << dropped_packets << std::endl <<
        "\tdropped packet events: " << dropped_packet_events << std::endl;
    }
}


uint32_t DCA1000Handler::get_packet_sequence_number(std::vector<uint8_t>& buffer){
    //get the sequence number
    std::uint32_t packet_sequence_number = 
        static_cast<uint32_t>(buffer[3]) << 24 |
        static_cast<uint32_t>(buffer[2]) << 16 |
        static_cast<uint32_t>(buffer[1]) << 8 |
        static_cast<uint32_t>(buffer[0]);
    packet_sequence_number = le32toh(packet_sequence_number);

    return packet_sequence_number;
}

uint64_t DCA1000Handler::get_packet_byte_count(std::vector<uint8_t>& buffer){
    
    //get the byte count
    uint64_t packet_byte_count = 
            static_cast<uint64_t>(buffer[9]) << 40 |
            static_cast<uint64_t>(buffer[8]) << 32 |
            static_cast<uint64_t>(buffer[7]) << 24 |
            static_cast<uint64_t>(buffer[6]) << 16 |
            static_cast<uint64_t>(buffer[5]) << 8  |
            static_cast<uint64_t>(buffer[4]);
        packet_byte_count = le64toh(packet_byte_count);

    return packet_byte_count;
}

/**
 * @brief 
 * @note Assumes that the frame_byte_buffer is initialized with zeros for each new frame
 * 
 * @param packet_byte_count the byte count from the most recently received packets
 * (i.e. the number of bytes that were supposed to have been received prior to the current
 * packet)
 */
void DCA1000Handler::zero_pad_frame_byte_buffer(std::uint64_t packet_byte_count){

    //determin the number of bytes to fill in
    std::uint64_t bytes_to_fill = packet_byte_count - adc_data_byte_count;

    //make sure we won't overflow the frame byte buffer
    std::uint64_t bytes_remaining = bytes_per_frame - next_frame_byte_buffer_idx;

    //room in the buffer
    if(bytes_remaining > bytes_to_fill){
        next_frame_byte_buffer_idx += bytes_to_fill;
    }else
    {
        //reset the frame byte buffer
        save_frame_byte_buffer();

        // //reset the index
        // if(bytes_remaining != bytes_to_fill){
        //     (next_frame_byte_buffer_idx + bytes_to_fill) % bytes_per_frame;
        // }
    }
    
    //update the received byte total
    adc_data_byte_count += bytes_to_fill;

}

/**
 * @brief saves the latest frame byte buffer into the 
 * latest_frame_byte_buffer variable, resets the frame_byte_buffer
 * and next_frame_byte_buffer_idx varialbes, and sets the
 * new_frame_available variable to true
 * 
 * @param print_system_status on True, prints status
 * 
 */
void DCA1000Handler::save_frame_byte_buffer(bool print_system_status){

    std::unique_lock<std::mutex> new_frame_available_unique_lock(
        new_frame_available_mutex,
        std::defer_lock
    );
    std::unique_lock<std::mutex> adc_data_cube_unique_lock(
        adc_data_cube_mutex,
        std::defer_lock
    );

    //copy the frame byte buffer into the latest frame byte buffer
    latest_frame_byte_buffer = frame_byte_buffer;

    //reset the frame byte buffer
    frame_byte_buffer = std::vector<uint8_t>(bytes_per_frame,0);

    //rest the next frame byte buffer idex
    next_frame_byte_buffer_idx = 0;

    //specify that a new frame is available
    new_frame_available_unique_lock.lock();
    new_frame_available = true;
    new_frame_available_unique_lock.unlock();

    //increment the frame tracking
    received_frames += 1;

    adc_data_cube_unique_lock.lock();
    if (system_config_reader.getSDKMajorVersion() == 2){
        update_latest_adc_cube_interleaved();
    } 
    // 2 lane (sdk 3+/IWR6843,IWR1843)
    else if (system_config_reader.getSDKMajorVersion() == 3)
    {
        // update_latest_adc_cube_interleaved();
        update_latest_adc_cube_noninterleaved();
    }
    else{
        std::cout << "DCA1000Handler::save_frame_byte_buffer(): invalid SDK major version" << std::endl;
        return;
    }
    
    adc_data_cube_unique_lock.unlock();

    if(print_system_status){
        print_status();
    }

    if(save_to_file){
        write_adc_data_cube_to_file();
    }
}

std::vector<std::int16_t> DCA1000Handler::convert_from_bytes_to_ints(
    std::vector<uint8_t>& in_vector)
{
    std::vector<std::int16_t> out_vector(in_vector.size() / 2,0);
    for (size_t i = 0; i < in_vector.size()/2; i++)
    {
        out_vector[i] = (
            (in_vector[i * 2]) | 
            (in_vector[i * 2 + 1] << 8)
        );

        //TODO: add in either le16toh() or be16toh() to preserve compatibility
        out_vector[i] = le16toh(out_vector[i]);
    }
    return out_vector;
}

/**
 * @brief Re-shapes a 1D vector into 2D vector, filling in the rows first
 * 
 * @param in_vector 
 * @param num_rows 
 * @return std::vector<std::vector<std::int16_t>> 
 */
std::vector<std::vector<std::int16_t>> DCA1000Handler::reshape_to_2D(
    std::vector<std::int16_t>& in_vector,
    size_t num_rows)
{
    std::vector<std::vector<std::int16_t>> out_vector(
        num_rows, std::vector<std::int16_t>(
            in_vector.size() / num_rows,0
        )
    );

    size_t in_vector_idx = 0;
    size_t row_idx = 0;
    size_t col_idx = 0;

    while (in_vector_idx < in_vector.size())
    {
        out_vector[row_idx][col_idx] = in_vector[in_vector_idx];

        row_idx += 1;

        if(row_idx >= num_rows){
            row_idx = 0;
            col_idx += 1;
        }

        in_vector_idx += 1;
    }
    
    return out_vector;
}

/**
 * @brief Interleave data that was stored in a non-interleaved format
 * 
 * @param in_vector data stored in a 4xM array where the columns
 * represent non-interleaved data in the pattern
 * [Rx0-samp0-I, Rx0-samp1-I,Rx0-samp0-Q,Rx0-samp1-Q]
 * @return std::vector<std::complex<std::int16_t>> interleaved data
 * which can be indexed by [sample, rx, chirp]
 * @note Assumes that there are an even number of samples per chirp 
 * (or that at least 2 antennas are active)
 */
std::vector<std::complex<std::int16_t>> DCA1000Handler::interleave_data(
        std::vector<std::vector<std::int16_t>>& in_vector)
{
    std::vector<std::complex<std::int16_t>> out_vector(
        samples_per_chirp * chirps_per_frame * num_rx_channels,
        std::complex<std::int16_t>(0,0)
    );

    size_t idx;
    for (size_t i = 0; i < in_vector[0].size(); i++)
    {
        idx = i * 2;
        //1st col - 1st real sample
        out_vector[idx].real(
            in_vector[0][i]
        );
        //2nd col - 2nd real sample
        out_vector[idx+1].real(
            in_vector[1][i]
        );
        //3rd col - 1st complex sample
        out_vector[idx].imag(
            in_vector[2][i]
        );
        //4th col - 2nd complex sample
        out_vector[idx+1].imag(
            in_vector[3][i]
        );
    }

    return out_vector;
}

/**
 * @brief Update the latest adc cube for a buffer generated by streaming
 * data in the "interleaved" format (applies to IWR1443)
 * 
 */
void DCA1000Handler::update_latest_adc_cube_interleaved(void)
{   
    //convert data from bytes to ints
    std::vector<std::int16_t> adc_data_ints = convert_from_bytes_to_ints(latest_frame_byte_buffer);
        
    //reshape it into lvds lanes [Rx1-4 real, Rx1-4 complex]
    std::vector<std::vector<std::int16_t>> adc_data_reshaped = reshape_to_2D(
        adc_data_ints,num_rx_channels * 2
    );

    //update the adc data cube   
    for (size_t chirp_idx = 0; chirp_idx < chirps_per_frame; chirp_idx++)
    {
        for (size_t sample_idx = 0; sample_idx < samples_per_chirp; sample_idx++)
        {   
            size_t idx = (chirp_idx * samples_per_chirp + sample_idx);
            //determine the index in the 2D reshaped buffer
            for (size_t rx_idx = 0; rx_idx < num_rx_channels; rx_idx++)
            {
                //set the real value
                adc_data_cube[rx_idx][sample_idx][chirp_idx].real(
                    adc_data_reshaped[rx_idx][idx]
                );

                //set the imaginary value
                adc_data_cube[rx_idx][sample_idx][chirp_idx].imag(
                    adc_data_reshaped[rx_idx + num_rx_channels][idx]
                );
            }
            
        }   
    }
}

/**
 * @brief Update the latest adc cube for a buffer generated by streaming
 * data in the "non-interleaved" format (applies to IWR183)
 * 
 */
void DCA1000Handler::update_latest_adc_cube_noninterleaved(void){

    //convert the byte data into integers
    std::vector<std::int16_t> adc_data_ints = convert_from_bytes_to_ints(latest_frame_byte_buffer);

    //reshape it into the lvds lanes [Rx0-samp0-I, Rx0-samp1-I,Rx0-samp0-Q,Rx0-samp1-Q]
    std::vector<std::vector<std::int16_t>> adc_data_reshaped = 
        reshape_to_2D(
            adc_data_ints,4
        );

    std::vector<std::complex<std::int16_t>> interleaved_data = 
        interleave_data(adc_data_reshaped);
    

    //update the adc data cube
    size_t idx = 0;
    for (size_t chirp_idx = 0; chirp_idx < chirps_per_frame; chirp_idx++)
    {
        for (size_t rx_idx = 0; rx_idx < num_rx_channels; rx_idx++)
        {   
            for (size_t sample_idx = 0; sample_idx < samples_per_chirp; sample_idx++)
            {
                //set the real value
                adc_data_cube[rx_idx][sample_idx][chirp_idx] = 
                    interleaved_data[idx];

                //set the imaginary value
                adc_data_cube[rx_idx][sample_idx][chirp_idx] = 
                    interleaved_data[idx];
                
                //update the idx counter
                idx++;
            }
            
        }
        
    }
}

std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> DCA1000Handler::get_latest_adc_data_cube(void){
    return adc_data_cube;
}

bool DCA1000Handler::init_out_file(){

    adc_cube_out_file = std::make_shared<std::ofstream>("adc_data.bin", 
        std::ios::out | std::ofstream::binary | std::ios::trunc);

    if(adc_cube_out_file -> is_open() != true){
        std::cout << "Failed to open or create adc_data.bin file" << std::endl;
        return false;
    }

    raw_lvds_out_file = std::make_shared<std::ofstream>("LVDS_Raw_0.bin", 
        std::ios::out | std::ofstream::binary | std::ios::trunc);

    if(raw_lvds_out_file -> is_open() != true){
        std::cout << "Failed to open or create LVDS_Raw_0.bin file" << std::endl;
        return false;
    }

    return true;
}

void DCA1000Handler::write_adc_data_cube_to_file(void){
    
    //initialize real and complex values
    std::int16_t real = 0;
    std::int16_t imag = 0;

    //make sure that the adc_cube_out_file is open
    if(adc_cube_out_file -> is_open()){
        for(size_t chirp_idx = 0; chirp_idx < chirps_per_frame; chirp_idx++){
            for(size_t rx_idx=0; rx_idx < num_rx_channels; rx_idx++){
                for(size_t sample_idx = 0; sample_idx < samples_per_chirp; sample_idx++){

                    //write the real part
                    real = adc_data_cube[rx_idx][sample_idx][chirp_idx].real();
                    adc_cube_out_file -> write(
                        reinterpret_cast<const char*>(
                            &real),
                        sizeof(real)
                    );

                    //write the imag part
                    imag = adc_data_cube[rx_idx][sample_idx][chirp_idx].imag();
                    adc_cube_out_file -> write(
                        reinterpret_cast<const char*>(
                            &imag),
                        sizeof(imag)
                    );
                }
            }
        }
    }else{
        std::cerr << "adc_cube_out_file.bin is not open, failed to save ADC data" <<std::endl;
    }
}

void DCA1000Handler::write_vector_to_file(std::vector<std::int16_t> &vector){
    
    //make sure that the adc_cube_out_file is open
    if(adc_cube_out_file -> is_open()){
        for(size_t idx = 0; idx < vector.size(); idx++){

            //write the real part
            adc_cube_out_file -> write(
                reinterpret_cast<const char*>(
                    &vector[idx]),
                sizeof(vector[idx])
            );
        }
    }else{
        std::cerr << "adc_cube_out_file.bin is not open, failed to save ADC data" <<std::endl;
    }
}