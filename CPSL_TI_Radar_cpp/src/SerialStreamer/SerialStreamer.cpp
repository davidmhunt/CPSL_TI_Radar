#include "SerialStreamer.hpp"

using namespace std;
using namespace boost::asio;

/**
 * @brief Construct a new Serial Streamer:: Serial Streamer object
 * but leave it uninitialized
 * 
 */
SerialStreamer::SerialStreamer():
    initialized(false),
    new_frame_available(false),
    new_frame_available_mutex(),
    tlv_processing_mutex(),
    system_config_reader(), //will leave it uninitialized
    io_context(new boost::asio::io_context()),
    data_port(nullptr),
    serial_stream(),
    timeout(*io_context),
    serial_message_data_buffer(),
    header_data_bytes(32,0),
    header_data(8,0),
    header_version(""),
    header_totalPacketLen(0),
    header_platform(""),
    header_frameNumber(0),
    header_timeCPUCycles(0),
    header_numDetectedObj(0),
    header_numTLVs(0),
    header_subFrameNumber(0),
    have_previous_frame(false),
    previous_frame_number(0),
    missed_frame_count(0),
    tlv_detected_points_processor(),
    tlv_side_info_processor(),
    VALID_DETECTED_POINTS()
{}

/**
 * @brief Construct a new Serial Streamer:: Serial Streamer object
 * 
 * @param systemConfigReader initialized system config reader
 */
SerialStreamer::SerialStreamer(const SystemConfigReader & systemConfigReader):
    initialized(false),
    new_frame_available(false),
    new_frame_available_mutex(),
    tlv_processing_mutex(),
    system_config_reader(),
    io_context(new boost::asio::io_context()),
    data_port(nullptr),
    serial_stream(),
    timeout(*io_context),
    serial_message_data_buffer(),
    header_data_bytes(32,0),
    header_data(8,0),
    header_version(""),
    header_totalPacketLen(0),
    header_platform(""),
    header_frameNumber(0),
    header_timeCPUCycles(0),
    header_numDetectedObj(0),
    header_numTLVs(0),
    header_subFrameNumber(0),
    have_previous_frame(false),
    previous_frame_number(0),
    missed_frame_count(0),
    tlv_detected_points_processor(),
    tlv_side_info_processor(),
    VALID_DETECTED_POINTS()
{    
    initialize(systemConfigReader);
}

/**
 * @brief Copy Contructor
 * 
 * @param rhs 
 */
SerialStreamer::SerialStreamer(const SerialStreamer & rhs):
    initialized(rhs.initialized),
    new_frame_available(rhs.new_frame_available),
    new_frame_available_mutex(),
    tlv_processing_mutex(),
    io_context(rhs.io_context),
    data_port(rhs.data_port),
    system_config_reader(rhs.system_config_reader),
    serial_stream(), // `boost::asio::streambuf` does not support copying; initialize a fresh buffer
    timeout(*rhs.io_context),
    serial_message_data_buffer(rhs.serial_message_data_buffer),
    header_data_bytes(rhs.header_data_bytes),
    header_data(rhs.header_data),
    header_version(rhs.header_version),
    header_totalPacketLen(rhs.header_totalPacketLen),
    header_platform(rhs.header_platform),
    header_frameNumber(rhs.header_frameNumber),
    header_timeCPUCycles(rhs.header_timeCPUCycles),
    header_numDetectedObj(rhs.header_numDetectedObj),
    header_numTLVs(rhs.header_numTLVs),
    header_subFrameNumber(rhs.header_subFrameNumber),
    have_previous_frame(rhs.have_previous_frame),
    previous_frame_number(rhs.previous_frame_number),
    missed_frame_count(rhs.missed_frame_count),
    tlv_detected_points_processor(rhs.tlv_detected_points_processor),
    tlv_side_info_processor(rhs.tlv_side_info_processor),
    VALID_DETECTED_POINTS(rhs.VALID_DETECTED_POINTS)
{}

/**
 * @brief Assignment operator
 * 
 * @param rhs 
 * @return SerialStreamer& 
 */
SerialStreamer & SerialStreamer::operator=(const SerialStreamer & rhs){
    if(this!= & rhs){

        //close the cli port if it is open
        if(data_port.get() != nullptr &&
            data_port.use_count() == 1 && 
            data_port -> is_open())
        {
            data_port -> close();
        }

        // Copy other members
        initialized = rhs.initialized;
        new_frame_available = rhs.new_frame_available;
        //don't re-assign the mutex operators
        io_context = rhs.io_context;
        data_port = rhs.data_port;
        system_config_reader = rhs.system_config_reader;
        serial_message_data_buffer = rhs.serial_message_data_buffer;
        header_data_bytes = rhs.header_data_bytes;
        header_data = rhs.header_data;

        // Streambuf cannot be copied; ensure it’s reinitialized
        serial_stream.consume(serial_stream.size()); // Clear buffer contents
        timeout = boost::asio::deadline_timer(*io_context); // Reinitialize timeout with the new io_context
    }

    return *this;
}

/**
 * @brief Destroy the Serial Streamer:: Serial Streamer object
 * 
 */
SerialStreamer::~SerialStreamer()
{
    //TODO: Check if the serial port is running right now
    if(data_port.get() != nullptr && 
        data_port.use_count() == 1 &&
        data_port -> is_open()){
        data_port -> close();
    }
}

bool SerialStreamer::initialize(const SystemConfigReader & systemConfigReader){

    system_config_reader = systemConfigReader;

    //check to make sure that the cli port isn't already open
    if(data_port.get() != nullptr &&
        data_port.use_count() == 1 && 
        data_port -> is_open())
    {
        data_port -> close();
    }

    if(system_config_reader.initialized){
        data_port = std::make_shared<boost::asio::serial_port>(
            *io_context,system_config_reader.getRadarDataPort());
        initialized = set_serial_baud_rate(*data_port, system_config_reader.getRadarDataBaudRate());
        have_previous_frame = false;
        missed_frame_count = 0;
    } else{
        initialized = false;
        std::cerr << "attempted to initialize cli controller,\
            but system_config_reader was not initialized";
    }

    return initialized;
}

/**
 * @brief Process the next message of TLV data
 * @note new_frame_data flag must be checked to see if the new
 *  TLV frame data was actually valid
 * 
 * @return true new TLV frame data received successfully
 *  (check new_frame_available flag to see if data was valid though)
 * @return false new TLV frame data was not successfully received
 *  (usually due to a timeout) 
 */
bool SerialStreamer::process_next_message(void){

    //define unique locks for thread safety
    std::unique_lock<std::mutex> new_frame_available_unique_lock(
        new_frame_available_mutex,
        std::defer_lock
    );

    //get the next serial frame and load it into the serial_message_data_buffer
    if (!get_next_serial_frame()){
        return false;
    }

    //process the header
    if (!process_message_header()){
        return true;
    }


    //process all new TLVs; a valid frame is committed (under the TLV lock) only here
    if (!process_TLV_messages()){
        return true;
    }

    //denote a new frame is available
    new_frame_available_unique_lock.lock();
    new_frame_available = true;
    new_frame_available_unique_lock.unlock();

    return true;
}

/**
 * @brief Determine if a new frame's worth of TLV data
 *  is now available in a thread safe manner
 * 
 * @return true - a new frame is available
 * @return false - a new frame is not available
 */
bool SerialStreamer::check_new_frame_available(void){

    //create unique locks to access data in a thread safe manner
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

std::vector<std::vector<float>> SerialStreamer::tlv_get_latest_detected_points(void){

    //create the mutexes/locks to access data in a thread safe manner
    std::unique_lock<std::mutex> new_frame_available_unique_lock(
        new_frame_available_mutex,
        std::defer_lock
    );

    std::unique_lock<std::mutex> tlv_processing_unique_lock(
        tlv_processing_mutex,
        std::defer_lock
    );

    //access the latest detected points
    std::vector<std::vector<float>> latest_detected_points;
    tlv_processing_unique_lock.lock();
    latest_detected_points = tlv_detected_points_processor.detected_points;
    tlv_processing_unique_lock.unlock();

    //reset the new_frame_available flage
    new_frame_available_unique_lock.lock();
    new_frame_available = false;
    new_frame_available_unique_lock.unlock();

    return latest_detected_points;
}

/**
 * @brief Get the SNR/noise ([snr_dB, noise_dB] per point, same order as the
 *  detected points) from the latest frame. Empty if the demo doesn't send TLV type 7.
 * @note Doesn't reset the new_frame_available flag; call it before
 *  tlv_get_latest_detected_points() to read both for the same frame.
 * 
 * @return std::vector<std::vector<float>> 
 */
std::vector<std::vector<float>> SerialStreamer::tlv_get_latest_detected_points_side_info(void){

    std::lock_guard<std::mutex> tlv_processing_lock(tlv_processing_mutex);
    return tlv_side_info_processor.side_info;
}

/**
 * @brief Get the frame number from the header of the latest valid frame
 * 
 * @return uint32_t 
 */
uint32_t SerialStreamer::get_latest_frame_number(void){

    std::lock_guard<std::mutex> tlv_processing_lock(tlv_processing_mutex);
    return header_frameNumber;
}

/**
 * @brief Get the number of frames skipped (gaps in the header frame number)
 * since the streamer was initialized
 * 
 * @return uint32_t 
 */
uint32_t SerialStreamer::get_missed_frame_count(void){

    std::lock_guard<std::mutex> tlv_processing_lock(tlv_processing_mutex);
    return missed_frame_count;
}

/**
 * @brief Wait for the next complete message (indicated by 
 * receiving a magic word) and save the read data into the 
 * serial_message_data_buffer. Times out after the configured
 * serial_streaming timeout_ms (default 1s)
 * 
 * @return true on successful data capture
 * @return false on error or timeout during data capture
 */
bool SerialStreamer::get_next_serial_frame(void) {
    size_t bytes_transfered = 0;
    boost::system::error_code ec;

    // Set the timeout for the asynchronous read
    timeout.expires_from_now(boost::posix_time::millisec(
        system_config_reader.getRadarDataTimeoutMs()));

    // Start asynchronous read until the magic word is found
    async_read_until(*data_port, serial_stream, magic_word, 
        [this,&ec, &bytes_transfered](const boost::system::error_code& e, size_t transfered) {
            ec = e;
            bytes_transfered = transfered;

            if(!e){
                boost::system::error_code cancel_ec;
                this->timeout.cancel(cancel_ec);
            }
        }
    );

    // Set up the timeout to cancel the operation if it takes too long
    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            data_port->cancel();
        }
    });

    // Run the I/O context to process the asynchronous operations
    io_context->run();
    io_context->reset();

    // Check for errors and handle the results
    if (!ec) {

        //load data into the vector
        serial_message_data_buffer = std::vector<uint8_t>(bytes_transfered);
        boost::asio::buffer_copy(
            boost::asio::buffer(serial_message_data_buffer),
            serial_stream.data(),
            bytes_transfered
        );

        // Remove the received data from the buffer
        serial_stream.consume(bytes_transfered);

        return true;
    } else if (ec == boost::asio::error::operation_aborted) {
        // Timeout occurred
        std::cout << "SerialStreamer: Timeout while waiting for response" << std::endl;
        return false;
    } else {
        // Other errors
        std::cerr << "Error while reading response: " << ec.message() << std::endl;
        return false;
    }
}

/**
 * @brief Decode the latest frame message's header
 * @note Assumes that latest frame data bytes have
 * already been loaded in via the
 * get_next_serial_frame function
 * 
 * @return true on header successfully decoded
 * @return false on header error
 */
bool SerialStreamer::process_message_header(void){

    //confirm valid message (first received frame will not be)
    if(serial_message_data_buffer.size() <= 32){
        return false;
    }

    //get the header data bytes
    header_data_bytes.assign(
        serial_message_data_buffer.begin(),
        serial_message_data_buffer.begin() + 32
    );

    //reinterpret the data into uint32 type
    const uint32_t* data_ptr = reinterpret_cast<const uint32_t*>(header_data_bytes.data());

    // Append the reinterpreted data to header_data
    header_data.assign(data_ptr, data_ptr + 8);
    
    //convert from le32 to host format
    for (size_t i = 0; i < header_data.size(); i++)
    {
        header_data[i] = le32toh(header_data[i]);
    }

    //decode into pending_: nothing a reader can see changes until the whole
    //frame (header length and every TLV) has been validated
    pending_.version = uint32ToHex(header_data[0]);
    pending_.totalPacketLen = header_data[1];
    pending_.platform = uint32ToHex(header_data[2]);
    pending_.frameNumber = header_data[3];
    pending_.timeCPUCycles = header_data[4];
    pending_.numDetectedObj = header_data[5];
    pending_.numTLVs = header_data[6];
    pending_.subFrameNumber = header_data[7];

    if(system_config_reader.get_verbose()){
        print_status();
    }

    //check to ensure the message is valid
    return check_valid_message();
}

void SerialStreamer::print_status(void){

    std::cout <<
    "frame: " << pending_.frameNumber << std::endl <<
    "\tversion: " << pending_.version << std::endl <<
    "\ttotal Packet length: " << pending_.totalPacketLen << " bytes" << std::endl <<
    "\tplatform: " << pending_.platform << std::endl <<
    "\ttime (CPU cycles): " << pending_.timeCPUCycles << std::endl <<
    "\tDetected Objects: " << pending_.numDetectedObj << std::endl <<
    "\tNumber of TLVs: " << pending_.numTLVs << std::endl <<
    "\tSubframe number: " << pending_.subFrameNumber << std::endl;
}

/**
 * @brief Check's to make sure that the message and its header
 * are valid
 * @note Assumes that latest frame data bytes have
 * already been loaded in via the
 * get_next_serial_frame function and that the header
 * has been processed using the process_message_header
 * 
 * @return true on message is valid
 * @return false message is invalid
 */
bool SerialStreamer::check_valid_message(void){
    if(static_cast<size_t>(pending_.totalPacketLen) == 
        serial_message_data_buffer.size()){
            return true;
        }
    else{
        std::cout << "serialStreamer: invalid message" << std::endl;
        return false;
    }
}

/**
 * @brief Process all of the TLV messages 
 * @note Assumes that the serial data has already been loaded into the
 *  serial_message_data_buffer and that the header has been processed
 *  by calling the process_message_header() function
 * 
 */
bool SerialStreamer::process_TLV_messages(void){

    //start processing after the header
    size_t tlv_start_byte_idx = 32;
    uint32_t TLV_type;
    size_t TLV_len;

    //helper variables for processing tlv packets
    size_t start_idx;
    size_t end_idx;

    //decode into fresh processors; a frame without a given TLV (e.g. no
    //detections) then reports empty, never stale, data
    TLVDetectedPoints points;
    TLVDetectedPointsSideInfo side_info;

    for (size_t i = 0; i < pending_.numTLVs; i++)
    {
        //make sure the TLV header and payload fit in the received message
        if (tlv_start_byte_idx + 8 > serial_message_data_buffer.size()){
            std::cout << "SerialStreamer: TLV header past end of message" << std::endl;
            return false;
        }

        //get the next TLV type and length
        TLV_type = get_TLV_type(tlv_start_byte_idx);
        TLV_len = get_TLV_len(tlv_start_byte_idx);

        //create the tlv_data_vector
        start_idx = tlv_start_byte_idx + 8;
        end_idx = start_idx + TLV_len;
        if (end_idx > serial_message_data_buffer.size()){
            std::cout << "SerialStreamer: TLV (type " << TLV_type << ") length " << TLV_len
                      << " runs past end of message" << std::endl;
            return false;
        }
        std::vector<uint8_t> tlv_data(
            serial_message_data_buffer.begin() + start_idx,
            serial_message_data_buffer.begin() + end_idx
        );

        if (!process_TLV(tlv_data, TLV_type, points, side_info)){
            std::cout << "SerialStreamer: TLV (type " << TLV_type << ") payload of " << TLV_len
                      << " bytes is malformed" << std::endl;
            return false;
        }

        //increment the start byte index to process next tlv packet
        tlv_start_byte_idx += TLV_len + 8;
    }

    commit_frame(points, side_info);
    return true;
}

/**
 * @brief Publish a fully validated frame: header fields, TLV outputs and the
 * frame-number gap tracking change together under the TLV lock.
 */
void SerialStreamer::commit_frame(TLVDetectedPoints & points, TLVDetectedPointsSideInfo & side_info){

    std::lock_guard<std::mutex> tlv_processing_lock(tlv_processing_mutex);

    header_version = pending_.version;
    header_totalPacketLen = pending_.totalPacketLen;
    header_platform = pending_.platform;
    header_frameNumber = pending_.frameNumber;
    header_timeCPUCycles = pending_.timeCPUCycles;
    header_numDetectedObj = pending_.numDetectedObj;
    header_numTLVs = pending_.numTLVs;
    header_subFrameNumber = pending_.subFrameNumber;

    tlv_detected_points_processor.detected_points.swap(points.detected_points);
    tlv_detected_points_processor.valid_data = points.valid_data;
    VALID_DETECTED_POINTS = points.valid_data;
    tlv_side_info_processor.side_info.swap(side_info.side_info);
    tlv_side_info_processor.valid_data = side_info.valid_data;

    //track gaps in the frame number (dropped/corrupted frames)
    if (have_previous_frame && header_frameNumber != previous_frame_number + 1){
        uint32_t missed = header_frameNumber - previous_frame_number - 1;
        missed_frame_count += missed;
        std::cout << "SerialStreamer: frame number jumped from " << previous_frame_number
                  << " to " << header_frameNumber << " (" << missed_frame_count
                  << " missed in total)" << std::endl;
    }
    have_previous_frame = true;
    previous_frame_number = header_frameNumber;
}

bool SerialStreamer::process_TLV(
    std::vector<uint8_t>  & tlv_data,
    uint32_t tlv_type,
    TLVDetectedPoints & points,
    TLVDetectedPointsSideInfo & side_info){

        switch (tlv_type)
        {
        case TLVCodes::DETECTED_POINTS:
            points.process(tlv_data);
            return points.valid_data;

        case TLVCodes::DETECTED_POINTS_SIDE_INFO:
            side_info.process(tlv_data);
            return side_info.valid_data;

        default:
            return true;
        }
}

/**
 * @brief Get the TLV type of a given TLV packet
 * 
 * @param tlv_start_byte_idx the index of the first byte for the given TLV
 *  packet in the serial_message_data_buffer
 * @return uint32_t the uint32_t value corresponding to the TLV type
 *  (see TLVProcessing for decoding the TLV type)
 */
uint32_t SerialStreamer::get_TLV_type(size_t tlv_start_byte_idx){

    size_t i = tlv_start_byte_idx;
    uint32_t value = (static_cast<uint32_t>(serial_message_data_buffer[i]) << 0) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 1]) << 8) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 2]) << 16) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 3]) << 24);

    return le32toh(value);
}

/**
 * @brief Get the length in bytes of a TLV packet (excludes the 
 *  bytes for the TLV type and TLV length data)
 * 
 * @param tlv_start_byte_idx the index of the first byte for the given TLV
 *  packet in the serial_message_data_buffer
 * @return size_t the length (in bytes) of a TLV packet (excludes the 
 *  bytes for the TLV type and TLV length data)
 */
size_t SerialStreamer::get_TLV_len(size_t tlv_start_byte_idx){

    size_t i = tlv_start_byte_idx + 4;
    uint32_t value = (static_cast<uint32_t>(serial_message_data_buffer[i]) << 0) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 1]) << 8) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 2]) << 16) |
        (static_cast<uint32_t>(serial_message_data_buffer[i + 3]) << 24);

    return static_cast<size_t>(le32toh(value));
}

/**
 * @brief Convert a uint32_t into a string of its hexidecimal representation
 * 
 * @param value the uint32_t value to get a hex representation of
 * @return std::string 
 */
std::string SerialStreamer::uint32ToHex(uint32_t value) {
    std::stringstream ss;
    ss << std::hex << std::uppercase << 
        std::setw(8) << std::setfill('0') 
        << value;
    return ss.str();
}