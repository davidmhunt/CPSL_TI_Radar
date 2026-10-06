#include "DCA1000Handler.hpp"

#include <algorithm>
#include <sstream>

#include "Log.hpp"

/**
 * @brief Default constructor (un-initialized)
 */
DCA1000Handler::DCA1000Handler():
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
    raw_lvds_out_file(nullptr)
{}

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

/**
 * @brief Load the configs, open the output files and size the frame buffers,
 * without opening a socket or talking to the DCA1000. Radar::open calls it;
 * hardware-free tests call it alone and feed ingest_packet().
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
    return count_ > 0;
}

size_t DCA1000Handler::queued_frames(){
    std::lock_guard<std::mutex> lock(frame_mutex);
    return count_;
}

void DCA1000Handler::close_frames(){
    {
        std::lock_guard<std::mutex> lock(frame_mutex);
        closed_ = true;
    }
    frame_cv_.notify_all();
}

bool DCA1000Handler::take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                                std::chrono::steady_clock::time_point& completed_at){
    return take_frame(out, index, missing_bytes, completed_at,
                      std::chrono::steady_clock::time_point::min());
}

bool DCA1000Handler::take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                                std::chrono::steady_clock::time_point& completed_at,
                                std::chrono::steady_clock::time_point deadline){
    //take the frame under the one lock the producer publishes with, so a
    //frame published in between is never lost or delivered stale. The wait
    //re-checks the queue under that lock, so a wake-up cannot be missed.
    std::unique_lock<std::mutex> lock(frame_mutex);
    if(deadline != std::chrono::steady_clock::time_point::min()){
        frame_cv_.wait_until(lock, deadline, [this] { return count_ > 0 || closed_; });
    }
    if(count_ == 0 || closed_){
        return false;
    }
    Slot& s = queue_[head_];
    out.swap(s.cube);  //the caller's old buffer stays in the slot as a free buffer
    index = s.index;
    missing_bytes = s.missing;
    completed_at = s.completed_at;
    head_ = (head_ + 1) % queue_.size();
    count_ -= 1;
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
        received_frames = 0;

        //the frame buffer pool, allocated once here: the work buffer and the
        //runtime.frame_queue_depth queue slots, each indexed by [Rx channel,
        //sample, chirp]
        const Cube shaped(
            num_rx_channels, std::vector<std::vector<std::complex<std::int16_t>>>(
                samples_per_chirp, std::vector<std::complex<std::int16_t>>(
                    chirps_per_frame, std::complex<std::int16_t>(0, 0)
                )
            )
        );
        {
            std::lock_guard<std::mutex> lock(frame_mutex);
            work_ = Slot();
            work_.cube = shaped;
            const size_t depth = std::max<size_t>(1, system_config_reader.get_frame_queue_depth());
            queue_.assign(depth, Slot());
            for(Slot& s : queue_){
                s.cube = shaped;
            }
            head_ = 0;
            count_ = 0;
            closed_ = false;
        }

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
        last_status_ = std::chrono::steady_clock::time_point{};
        converter_.configure(num_rx_channels, samples_per_chirp, chirps_per_frame,
                             system_config_reader.getBoard().lvds.layout,
                             system_config_reader.getBoard().lvds.iq_order);
    }else{
        cpsl::radar::log_error("attempted to initialize DCA1000 Handler buffers, ",
                               "but radar_config_reader wasn't initialized");
    }
}

//one debug line with the cumulative counters (the same ones Radar::stats()
//and --stats report); called at most once per kStatusPeriod
void DCA1000Handler::print_status(){
    const FrameAssembler::Stats stats = assembler_.get_stats();
    std::ostringstream o;
    o << "DCA1000: frames " << received_frames
      << ", packets " << stats.received_packets
      << ", data bytes " << stats.adc_data_byte_count
      << ", dropped packets " << stats.dropped_packets
      << " (" << stats.dropped_packet_events << " events)"
      << ", late " << stats.late_packets
      << ", duplicate " << stats.duplicate_packets
      << ", incomplete frames " << stats.incomplete_frames
      << ", skipped frames " << stats.skipped_frames
      << ", rx overruns " << (source_ ? source_->overrun_count() : 0);
    cpsl::radar::log_debug(o.str());
}


/**
 * @brief Convert the frame the assembler just completed, publish it (cube,
 * flag, index, missing bytes, completion time and a counter snapshot change
 * together under frame_mutex), log the debug status line (at most once per
 * kStatusPeriod) and save it.
 *
 * @param index frame index (stream offset / bytes_per_frame)
 * @param missing_bytes zero-filled bytes in the frame
 */
void DCA1000Handler::save_frame_byte_buffer(uint64_t index, size_t missing_bytes){

    //increment the frame tracking
    received_frames += 1;

    //convert in place into the work buffer, outside the lock (only this
    //thread touches work_)
    converter_.convert(assembler_.get_frame_bytes(), work_.cube);
    const std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now();
    work_.index = index;
    work_.missing = missing_bytes;
    work_.completed_at = now;

    //the consumer may take the buffer as soon as it is published, so the file
    //gets it first
    if(save_adc_frames){
        write_adc_data_cube_to_file(work_.cube);
    }

    if(publish_hook_){
        publish_hook_();
    }

    //publish: swap the work buffer into the queue's next slot under
    //frame_mutex, so a frame is never visible before its cube; the slot's
    //previous (free or dropped) buffer becomes the next work buffer. The
    //consumer is woken only after that (notifying earlier could be lost: a
    //woken consumer would find the queue empty and wait again).
    {
        std::lock_guard<std::mutex> lock(frame_mutex);
        if(count_ == queue_.size()){
            //the oldest published frame was never taken: drop it
            head_ = (head_ + 1) % queue_.size();
            count_ -= 1;
            stats_.frames_overwritten += 1;
        }
        const size_t tail = (head_ + count_) % queue_.size();
        std::swap(queue_[tail], work_);
        count_ += 1;
        stats_.assembler = assembler_.get_stats();
        stats_.frames = received_frames;
    }
    frame_cv_.notify_one();
    last_frame_ns_.store(std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count(),
                         std::memory_order_relaxed);

    //periodic, not per frame: a log line per frame (or per dropped packet)
    //would stall this thread on the sink in a drop storm (design P10)
    if(cpsl::radar::log_enabled(cpsl::radar::LogLevel::debug) && now - last_status_ >= kStatusPeriod){
        last_status_ = now;
        print_status();
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

void DCA1000Handler::write_adc_data_cube_to_file(const Cube& adc_data_cube){
    
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
