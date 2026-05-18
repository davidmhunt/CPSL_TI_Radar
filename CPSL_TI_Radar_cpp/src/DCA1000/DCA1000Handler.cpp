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
    socket_(),
    udp_packet_buffer(),
    udp_packet_size(1472),
    received_frames(0),
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
    socket_(),
    udp_packet_buffer(),
    udp_packet_size(1472),
    received_frames(0),
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
    adc_data_cube_mutex(),       //mutexes aren't copyable
    system_config_reader(rhs.system_config_reader),
    radar_config_reader(rhs.radar_config_reader),
    DCA_fpgaIP(rhs.DCA_fpgaIP),
    DCA_systemIP(rhs.DCA_systemIP),
    DCA_cmdPort(rhs.DCA_cmdPort),
    DCA_dataPort(rhs.DCA_dataPort),
    socket_(), // DCA1000Socket is not copyable — fresh instance
    udp_packet_buffer(rhs.udp_packet_buffer),
    udp_packet_size(rhs.udp_packet_size),
    received_frames(rhs.received_frames),
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
        //close file streams if we're the sole owner
        if (save_to_file) {
            if (adc_cube_out_file && adc_cube_out_file.use_count() == 1 &&
                adc_cube_out_file->is_open())
                adc_cube_out_file->close();
            if (raw_lvds_out_file && raw_lvds_out_file.use_count() == 1 &&
                raw_lvds_out_file->is_open())
                raw_lvds_out_file->close();
        }

        initialized          = rhs.initialized;
        new_frame_available  = rhs.new_frame_available;
        //don't re-assign mutexes
        system_config_reader = rhs.system_config_reader;
        radar_config_reader  = rhs.radar_config_reader;
        DCA_fpgaIP           = rhs.DCA_fpgaIP;
        DCA_systemIP         = rhs.DCA_systemIP;
        DCA_cmdPort          = rhs.DCA_cmdPort;
        DCA_dataPort         = rhs.DCA_dataPort;
        // socket_ is not copyable — leave as-is (fresh/uninitialized state)
        udp_packet_buffer    = rhs.udp_packet_buffer;
        udp_packet_size      = rhs.udp_packet_size;
        received_frames      = rhs.received_frames;
        bytes_per_frame      = rhs.bytes_per_frame;
        samples_per_chirp    = rhs.samples_per_chirp;
        chirps_per_frame     = rhs.chirps_per_frame;
        num_rx_channels      = rhs.num_rx_channels;
        save_to_file         = rhs.save_to_file;
        adc_cube_out_file    = rhs.adc_cube_out_file;
        raw_lvds_out_file    = rhs.raw_lvds_out_file;
        adc_data_cube        = rhs.adc_data_cube;
        latest_frame_byte_buffer = rhs.latest_frame_byte_buffer;
    }
    return *this;
}

/**
 * @brief Destroy the DCA1000Handler::DCA1000Handler object
 * 
 */
DCA1000Handler::~DCA1000Handler() {
    // socket_ destructor handles RX thread join and socket close

    if (save_to_file) {
        if (adc_cube_out_file && adc_cube_out_file.use_count() == 1 &&
            adc_cube_out_file->is_open())
            adc_cube_out_file->close();
        if (raw_lvds_out_file && raw_lvds_out_file.use_count() == 1 &&
            raw_lvds_out_file->is_open())
            raw_lvds_out_file->close();
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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

        //get the status
        uint16_t status = static_cast<uint16_t>(rcv_data[5]) << 8;
        status = status | static_cast<uint16_t>(rcv_data[4]);

        //confirm success
        if (status == 0){
            socket_.start_rx();
            return true;
        }else{
            return false;
        }
    } else{
        return false;
    }
}

bool DCA1000Handler::send_recordStop(){

    // Stop RX thread before telling DCA1000 to stop (avoids recvfrom blocking on exit)
    socket_.stop_rx();

    //get the command
    std::vector<uint8_t> cmd = DCA1000Commands::construct_command(
                                        DCA1000Commands::RECORD_STOP);

    //send command
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

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

    //LVDS mode — 4 lane for IWR1443, 2 lane for IWR1843/IWR6843
    if (system_config_reader.getBoardType() == "IWR1443") {
        data[1] = 0x01; // 4-lane
    } else if (system_config_reader.getBoardType() == "IWR1843" ||
               system_config_reader.getBoardType() == "IWR6843") {
        data[1] = 0x02; // 2-lane
    } else {
        std::cerr << "DCA1000Handler::send_configFPGAGen(): unrecognized board_type \""
                  << system_config_reader.getBoardType() << "\"" << std::endl;
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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){

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
    socket_.send_command(cmd);

    //get the response
    std::vector<uint8_t> rcv_data(8,0);
    if (socket_.receive_response(rcv_data)){
        
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

    // Pop next packet from the socket ring buffer (blocks up to 500 ms)
    uint8_t pkt_buf[1472];
    int received_bytes = 0;
    if (!socket_.pop_packet(pkt_buf, received_bytes, 500)) return false;

    // Delegate sequence checking and frame assembly to FrameAssembler
    int frames_completed = assembler_.push_packet(pkt_buf, received_bytes);
    for (int i = 0; i < frames_completed; i++) {
        save_frame_byte_buffer();
    }

    // Write entire ADC payload to raw LVDS file in one syscall
    if (save_to_file && received_bytes > 10) {
        raw_lvds_out_file->write(
            reinterpret_cast<const char*>(pkt_buf + 10),
            static_cast<std::streamsize>(received_bytes - 10)
        );
    }

    return true;
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

bool DCA1000Handler::init_sockets() {
    return socket_.init(DCA_fpgaIP, DCA_systemIP, DCA_cmdPort, DCA_dataPort);
}

/**
 * @brief Send a series of commands to the DCA1000 to configure it
 * 
 * @return true - DCA1000 successfully configured
 * @return false - DCA1000 not successfully configured
 */
bool DCA1000Handler::configure_DCA1000(){

    if (!socket_.is_initialized()) {
        std::cerr << "attempted to configure DCA1000 but socket is not initialized" << std::endl;
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
    if(send_configPacketData(udp_packet_size,100) != true){ //previously 25
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

void DCA1000Handler::init_buffers()
{
    if(radar_config_reader.initialized){
        bytes_per_frame = radar_config_reader.get_bytes_per_frame();
        samples_per_chirp = radar_config_reader.get_samples_per_chirp();
        chirps_per_frame = radar_config_reader.get_chirps_per_frame();
        num_rx_channels = radar_config_reader.get_num_rx_antennas();

        //configure the udp packet buffer
        udp_packet_buffer = std::vector<uint8_t>(udp_packet_size, 0);

        //configure processing of completed frames
        latest_frame_byte_buffer = std::vector<uint8_t>(bytes_per_frame, 0);
        new_frame_available = false;
        received_frames = 0;

        //adc_cube buffer — indexed by [Rx channel, sample, chirp]
        adc_data_cube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>(
            num_rx_channels, std::vector<std::vector<std::complex<std::int16_t>>>(
                samples_per_chirp, std::vector<std::complex<std::int16_t>>(
                    chirps_per_frame, std::complex<std::int16_t>(0, 0)
                )
            )
        );

        assembler_.configure(bytes_per_frame);
        converter_.configure(num_rx_channels, samples_per_chirp, chirps_per_frame,
                             system_config_reader.getBoardType());
    }else{
        std::cerr << "attempted to initialize DCA1000 Handler buffers,\
        but radar_config_reader wasn't initialized";
    }
}

void DCA1000Handler::print_status(){
    if(system_config_reader.get_verbose()){
        auto stats = assembler_.get_stats();
        std::cout <<
        "frame: " << received_frames << std::endl <<
        "\tpackets: " << stats.received_packets << std::endl <<
        "\tdata bytes: " << stats.adc_data_byte_count << std::endl <<
        "\tdropped packets: " << stats.dropped_packets << std::endl <<
        "\tdropped packet events: " << stats.dropped_packet_events << std::endl <<
        "\trx_overrun_count: " << socket_.get_overrun_count() << std::endl;
    }
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

    //specify that a new frame is available
    new_frame_available_unique_lock.lock();
    new_frame_available = true;
    new_frame_available_unique_lock.unlock();

    //increment the frame tracking
    received_frames += 1;

    adc_data_cube_unique_lock.lock();
    adc_data_cube = converter_.convert(assembler_.get_frame_bytes());
    adc_data_cube_unique_lock.unlock();

    if(print_system_status){
        print_status();
    }

    if(save_to_file){
        write_adc_data_cube_to_file();
    }
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