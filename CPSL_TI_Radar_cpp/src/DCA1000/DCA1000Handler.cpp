#include "DCA1000Handler.hpp"

#include <sstream>

#include "Log.hpp"

/**
 * @brief Default constructor (un-initialized)
 */
DCA1000Handler::DCA1000Handler():
    initialized(false),
    new_frame_available(false),
    frame_mutex(),
    system_config_reader(),
    radar_config_reader(),
    DCA_fpgaIP(""),
    DCA_systemIP(""),
    DCA_cmdPort(-1),
    DCA_dataPort(-1),
    socket_(),
    udp_packet_size(1472),
    received_frames(0),
    bytes_per_frame(0),
    samples_per_chirp(0),
    chirps_per_frame(0),
    num_rx_channels(4),
    save_adc_frames(false),
    save_raw_lvds(false),
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
    frame_mutex(),
    system_config_reader(),
    radar_config_reader(),
    DCA_fpgaIP(""),
    DCA_systemIP(""),
    DCA_cmdPort(-1),
    DCA_dataPort(-1),
    socket_(),
    udp_packet_size(1472),
    received_frames(0),
    bytes_per_frame(0),
    samples_per_chirp(0),
    chirps_per_frame(0),
    num_rx_channels(4),
    save_adc_frames(false),
    save_raw_lvds(false),
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
    frame_mutex(), //mutexes aren't copyable
    system_config_reader(rhs.system_config_reader),
    radar_config_reader(rhs.radar_config_reader),
    DCA_fpgaIP(rhs.DCA_fpgaIP),
    DCA_systemIP(rhs.DCA_systemIP),
    DCA_cmdPort(rhs.DCA_cmdPort),
    DCA_dataPort(rhs.DCA_dataPort),
    socket_(), // DCA1000Socket is not copyable — fresh instance
    udp_packet_size(rhs.udp_packet_size),
    received_frames(rhs.received_frames),
    bytes_per_frame(rhs.bytes_per_frame),
    samples_per_chirp(rhs.samples_per_chirp),
    chirps_per_frame(rhs.chirps_per_frame),
    num_rx_channels(rhs.num_rx_channels),
    save_adc_frames(rhs.save_adc_frames),
    save_raw_lvds(rhs.save_raw_lvds),
    adc_cube_out_file(rhs.adc_cube_out_file),
    raw_lvds_out_file(rhs.raw_lvds_out_file),
    adc_data_cube(rhs.adc_data_cube),
    latest_frame_byte_buffer(rhs.latest_frame_byte_buffer)
{}

DCA1000Handler & DCA1000Handler::operator=(const DCA1000Handler & rhs){
    if(this != &rhs){
        //close file streams if we're the sole owner
        if (adc_cube_out_file && adc_cube_out_file.use_count() == 1 &&
            adc_cube_out_file->is_open())
            adc_cube_out_file->close();
        if (raw_lvds_out_file && raw_lvds_out_file.use_count() == 1 &&
            raw_lvds_out_file->is_open())
            raw_lvds_out_file->close();

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
        udp_packet_size      = rhs.udp_packet_size;
        received_frames      = rhs.received_frames;
        bytes_per_frame      = rhs.bytes_per_frame;
        samples_per_chirp    = rhs.samples_per_chirp;
        chirps_per_frame     = rhs.chirps_per_frame;
        num_rx_channels      = rhs.num_rx_channels;
        save_adc_frames      = rhs.save_adc_frames;
        save_raw_lvds        = rhs.save_raw_lvds;
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
    close_output_files();
}

bool DCA1000Handler::stop(){
    bool ok = true;
    try {
        if(initialized){
            //joins the RX thread, then tells the DCA1000 to stop
            ok = send_recordStop();
            if(!ok){
                cpsl::radar::log_warn("DCA1000Handler: recordStop was not acknowledged");
            }
        } else {
            socket_.stop_rx();
        }
    } catch (const std::exception& e) {
        cpsl::radar::log_error("DCA1000Handler: error while stopping: ", e.what());
        ok = false;
    }
    output_files_ok_ = close_output_files();
    if(!output_files_ok_){
        ok = false;
    }
    return ok;
}

/**
 * @brief Flush and close the output files this handler owns (shared copies
 * are left to their last owner). Safe to call again; never throws.
 *
 * @return false if a flush or close failed
 */
bool DCA1000Handler::close_output_files(){
    bool ok = true;
    for (std::shared_ptr<std::ofstream>* f : {&adc_cube_out_file, &raw_lvds_out_file}) {
        try {
            if (*f && f->use_count() == 1 && (*f)->is_open()) {
                (*f)->flush();
                (*f)->close();
                if ((*f)->fail()) {
                    cpsl::radar::log_error("DCA1000Handler: failed to flush/close an output file");
                    ok = false;
                }
            }
        } catch (const std::exception& e) {
            cpsl::radar::log_error("DCA1000Handler: error closing an output file: ", e.what());
            ok = false;
        }
    }
    return ok;
}

bool DCA1000Handler::initialize(
    const SystemConfigReader& systemConfigReader,
    const RadarConfigReader& radarConfigReader){

    initialized = false;

    //config, output files and frame buffers (no device I/O)
    if(!configure_pipeline(systemConfigReader, radarConfigReader)){
        return false;
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

    //set initialization status to true
    initialized = true;
    
    return true;
}

/**
 * @brief Load the configs, open the output files and size the frame buffers,
 * without opening a socket or talking to the DCA1000. initialize() starts
 * with this; hardware-free tests call it alone and feed ingest_packet().
 *
 * @return false if a config is not initialized or an output file can't be opened
 */
bool DCA1000Handler::configure_pipeline(
    const SystemConfigReader& systemConfigReader,
    const RadarConfigReader& radarConfigReader){

    //load the system configuration information
    system_config_reader = systemConfigReader;
    if(system_config_reader.initialized == false){
        return false;
    }
    load_config();

    //initialize file streaming
    if(save_adc_frames || save_raw_lvds){
        if(init_out_file() != true){
            return false;
        }
    }

    //load the radar config reader
    radar_config_reader = radarConfigReader;
    if(radar_config_reader.initialized == false){
        return false;
    }
    init_buffers();
    return true;
}

void DCA1000Handler::set_publish_hook(std::function<void()> hook){
    publish_hook_ = std::move(hook);
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

    //LVDS mode from the board descriptor (lvds.lanes): 0x01 = 4-lane, 0x02 = 2-lane
    const cpsl::radar::BoardDescriptor& board = system_config_reader.getBoard();
    if (!board.lvds.supported) {
        cpsl::radar::log_error("DCA1000Handler::send_configFPGAGen(): board ", board.name,
                               " has no LVDS capture support (lvds.supported false)");
        return false;
    }
    data[1] = board.lvds.lanes == 4 ? 0x01 : 0x02;

    //data transfer mode - LVDS capture
    data[2] = 0x01;

    //data capture mode - ethernet stream
    data[3] = 0x02;

    //data format mode - 16 bit
    data[4] = 0x03;

    //timer (dca1000.fpga_timer_s; 30 s on every shipped board)
    data[5] = static_cast<uint8_t>(board.dca1000.fpga_timer_s);

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

    ingest_packet(pkt_buf, received_bytes);
    return true;
}

/**
 * @brief Assemble one raw DCA1000 packet (10-byte header + payload): every
 * frame it completes is converted, published and saved; the payload also goes
 * to the raw LVDS file when enabled.
 */
void DCA1000Handler::ingest_packet(const uint8_t* data, int len){

    // Delegate sequence checking and frame assembly to FrameAssembler; every
    // completed frame reaches save_frame_byte_buffer() through the frame sink
    assembler_.push_packet(data, len);

    // Write entire ADC payload to raw LVDS file in one syscall
    if (save_raw_lvds && len > 10 && raw_lvds_out_file && raw_lvds_out_file->is_open()) {
        raw_lvds_out_file->write(
            reinterpret_cast<const char*>(data + 10),
            static_cast<std::streamsize>(len - 10)
        );
    }
}

/**
 * @brief Determine if a new frame's adc data cube is now available in a thread safe manner
 * 
 * @return true - a new frame is available
 * @return false - a new frame is not available
 */
bool DCA1000Handler::check_new_frame_available(){
    std::lock_guard<std::mutex> lock(frame_mutex);
    return new_frame_available;
}

/**
 * @brief Get the latest adc data cube and set the new_frame_available variable to false
 * 
 * @return std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> 
 */
std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> DCA1000Handler::get_latest_adc_cube()
{
    //copy the cube and clear the flag under the one lock the producer publishes
    //with, so a frame published in between is never lost or delivered stale
    std::lock_guard<std::mutex> lock(frame_mutex);
    new_frame_available = false;
    return adc_data_cube;
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
    save_adc_frames = system_config_reader.get_save_adc_frames();
    save_raw_lvds = system_config_reader.get_save_raw_lvds();
    udp_packet_size = system_config_reader.getBoard().dca1000.packet_bytes;

    cpsl::radar::log_debug("FPGA IP: ", DCA_fpgaIP, ", system IP: ", DCA_systemIP,
                           ", cmd port: ", DCA_cmdPort, ", data port: ", DCA_dataPort);
}

bool DCA1000Handler::init_sockets() {
    return socket_.init(DCA_fpgaIP, DCA_systemIP, DCA_cmdPort, DCA_dataPort,
                        system_config_reader.getDCARcvbufBytes());
}

/**
 * @brief Send a series of commands to the DCA1000 to configure it
 * 
 * @return true - DCA1000 successfully configured
 * @return false - DCA1000 not successfully configured
 */
bool DCA1000Handler::configure_DCA1000(){

    if (!socket_.is_initialized()) {
        cpsl::radar::log_error("attempted to configure DCA1000 but socket is not initialized");
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

    //send configure packet data (dca1000.packet_bytes / packet_delay_us; 1472 B / 100 us)
    const cpsl::radar::BoardDescriptor& board = system_config_reader.getBoard();
    if(send_configPacketData(udp_packet_size,
                             static_cast<uint16_t>(board.dca1000.packet_delay_us)) != true){
        return false;
    }

    //send config FPGA gen
    if(send_configFPGAGen() != true){
        return false;
    }

    //read the FPGA version
    float fpga_version = send_readFPGAVersion();

    if(fpga_version > 0){
        cpsl::radar::log_info("FPGA (firmware version: ", fpga_version, ") initialized successfully");
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

        //hold a frame open for a few packets past its end so a reordered packet can still land
        assembler_.configure(bytes_per_frame,
                             FrameAssembler::kDefaultReorderSlackPackets * (udp_packet_size - 10));
        assembler_.set_frame_sink([this](const std::vector<uint8_t>&, uint64_t, size_t) {
            save_frame_byte_buffer();
        });
        converter_.configure(num_rx_channels, samples_per_chirp, chirps_per_frame,
                             system_config_reader.getBoard().lvds.layout,
                             system_config_reader.getBoard().lvds.iq_order);
    }else{
        cpsl::radar::log_error("attempted to initialize DCA1000 Handler buffers, ",
                               "but radar_config_reader wasn't initialized");
    }
}

void DCA1000Handler::print_status(){
    if(cpsl::radar::log_enabled(cpsl::radar::LogLevel::debug)){
        auto stats = assembler_.get_stats();
        std::ostringstream o;
        o <<
        "frame: " << received_frames << "\n" <<
        "\tpackets: " << stats.received_packets << "\n" <<
        "\tdata bytes: " << stats.adc_data_byte_count << "\n" <<
        "\tdropped packets: " << stats.dropped_packets << "\n" <<
        "\tdropped packet events: " << stats.dropped_packet_events << "\n" <<
        "\tlate packets: " << stats.late_packets << "\n" <<
        "\tduplicate packets: " << stats.duplicate_packets << "\n" <<
        "\tincomplete frames: " << stats.incomplete_frames << "\n" <<
        "\tskipped frames: " << stats.skipped_frames << "\n" <<
        "\trx_overrun_count: " << socket_.get_overrun_count();
        cpsl::radar::log_debug(o.str());
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

    //increment the frame tracking
    received_frames += 1;

    //convert outside the lock, then publish: the cube and its flag change
    //together under frame_mutex, so the flag is never visible before its cube
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> cube =
        converter_.convert(assembler_.get_frame_bytes());

    if(publish_hook_){
        publish_hook_();
    }

    {
        std::lock_guard<std::mutex> lock(frame_mutex);
        adc_data_cube.swap(cube);
        new_frame_available = true;
    }

    if(print_system_status){
        print_status();
    }

    //only this thread writes adc_data_cube, so reading it here needs no lock
    if(save_adc_frames){
        write_adc_data_cube_to_file();
    }
}


bool DCA1000Handler::init_out_file(){

    //files go to output.dir (current directory when unset)
    if(save_adc_frames){
        const std::string path = system_config_reader.get_output_path("adc_data.bin");
        adc_cube_out_file = std::make_shared<std::ofstream>(path,
            std::ios::out | std::ofstream::binary | std::ios::trunc);

        if(adc_cube_out_file -> is_open() != true){
            cpsl::radar::log_error("Failed to open or create ", path);
            return false;
        }
    }

    if(save_raw_lvds){
        const std::string path = system_config_reader.get_output_path("LVDS_Raw_0.bin");
        raw_lvds_out_file = std::make_shared<std::ofstream>(path,
            std::ios::out | std::ofstream::binary | std::ios::trunc);

        if(raw_lvds_out_file -> is_open() != true){
            cpsl::radar::log_error("Failed to open or create ", path);
            return false;
        }
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
        cpsl::radar::log_error("adc_data.bin is not open, failed to save ADC data");
    }
}
