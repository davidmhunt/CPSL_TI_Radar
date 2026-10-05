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
    source_(nullptr),
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
    DCA1000Handler()
{
    initialize(configReader,radarConfigReader);
}

/**
 * @brief Destroy the DCA1000Handler::DCA1000Handler object
 * 
 */
DCA1000Handler::~DCA1000Handler() {
    // a UdpPacketSource's socket joins its RX thread and closes when the last owner goes
    if(source_){
        source_->stop();
    }
    close_output_files();
}

bool DCA1000Handler::stop(){
    bool ok = true;
    try {
        if(source_){
            //UDP: joins the RX thread, then tells the DCA1000 to stop
            const cpsl::radar::Status s = source_->stop();
            if(!s){
                cpsl::radar::log_warn("DCA1000Handler: ", s.message);
                ok = false;
            }
        }
    } catch (const std::exception& e) {
        cpsl::radar::log_error("DCA1000Handler: error while stopping: ", e.what());
        ok = false;
    }
    {
        //the worker thread has been joined: the assembler's counters are final
        std::lock_guard<std::mutex> lock(frame_mutex);
        stats_.assembler = assembler_.get_stats();
        stats_.frames = received_frames;
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
    const RadarConfigReader& radarConfigReader,
    std::shared_ptr<cpsl::radar::PacketSource> source){

    initialized = false;

    //config, output files and frame buffers (no device I/O)
    if(!configure_pipeline(systemConfigReader, radarConfigReader)){
        return false;
    }

    set_packet_source(source ? std::move(source)
                             : std::make_shared<cpsl::radar::UdpPacketSource>(system_config_reader));

    //open the sockets, then configure the DCA1000
    cpsl::radar::Status s = source_->open();
    if(s){
        s = source_->configure();
    }
    if(!s){
        cpsl::radar::log_error("DCA1000Handler: ", s.message);
        return false;
    }

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
    save_adc_frames = system_config_reader.get_save_adc_frames();
    save_raw_lvds = system_config_reader.get_save_raw_lvds();
    udp_packet_size = system_config_reader.getBoard().dca1000.packet_bytes;

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

void DCA1000Handler::set_packet_source(std::shared_ptr<cpsl::radar::PacketSource> source){
    source_ = std::move(source);
}

bool DCA1000Handler::send_recordStart(){
    if(!source_){
        return false;
    }
    const cpsl::radar::Status s = source_->start();
    if(!s){
        cpsl::radar::log_error("DCA1000Handler: ", s.message);
    }
    return static_cast<bool>(s);
}

/**
 * @brief 
 * 
 * @return true 
 * @return false 
 */
bool DCA1000Handler::process_next_packet(){

    // Pop the next packet from the source (UDP: the RX ring buffer; waits up to 500 ms)
    uint8_t pkt_buf[cpsl::radar::PacketSource::kMaxPacketBytes];
    int received_bytes = 0;
    if (!source_ || !source_->pop(pkt_buf, received_bytes, std::chrono::milliseconds(500))) return false;

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

bool DCA1000Handler::take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                                std::chrono::steady_clock::time_point& completed_at){
    std::lock_guard<std::mutex> lock(frame_mutex);
    if(!new_frame_available){
        return false;
    }
    new_frame_available = false;
    out = adc_data_cube;
    index = latest_index_;
    missing_bytes = latest_missing_;
    completed_at = latest_completed_at_;
    return true;
}

DCA1000Handler::Stats DCA1000Handler::get_stats(){
    std::lock_guard<std::mutex> lock(frame_mutex);
    return stats_;
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
        assembler_.set_frame_sink([this](const std::vector<uint8_t>&, uint64_t index, size_t missing) {
            save_frame_byte_buffer(index, missing);
        });
        {
            std::lock_guard<std::mutex> lock(frame_mutex);
            stats_ = Stats();
        }
        last_frame_ns_.store(0, std::memory_order_relaxed);
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
        "\trx_overrun_count: " << (source_ ? source_->overrun_count() : 0);
        cpsl::radar::log_debug(o.str());
    }
}


/**
 * @brief Convert the frame the assembler just completed, publish it (cube,
 * flag, index, missing bytes, completion time and a counter snapshot change
 * together under frame_mutex), print the debug status and save it.
 *
 * @param index frame index (stream offset / bytes_per_frame)
 * @param missing_bytes zero-filled bytes in the frame
 */
void DCA1000Handler::save_frame_byte_buffer(uint64_t index, size_t missing_bytes){

    //increment the frame tracking
    received_frames += 1;

    //convert outside the lock, then publish: the cube and its flag change
    //together under frame_mutex, so the flag is never visible before its cube
    Cube cube = converter_.convert(assembler_.get_frame_bytes());

    if(publish_hook_){
        publish_hook_();
    }

    const std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now();
    {
        std::lock_guard<std::mutex> lock(frame_mutex);
        adc_data_cube.swap(cube);
        if(new_frame_available){
            //latest wins: the previous frame was never taken
            stats_.frames_overwritten += 1;
        }
        new_frame_available = true;
        latest_index_ = index;
        latest_missing_ = missing_bytes;
        latest_completed_at_ = now;
        stats_.assembler = assembler_.get_stats();
        stats_.frames = received_frames;
    }
    last_frame_ns_.store(std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count(),
                         std::memory_order_relaxed);

    print_status();

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
