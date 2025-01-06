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
    tlv_detected_points_processor(),
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
    tlv_detected_points_processor(),
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
    tlv_detected_points_processor(rhs.tlv_detected_points_processor),
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
        data_port -> set_option(serial_port_base::baud_rate(921600));
        initialized = true;
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

    std::unique_lock<std::mutex> tlv_processing_unique_lock(
        tlv_processing_mutex,
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


    //process all new TLVs
    tlv_processing_unique_lock.lock();
    process_TLV_messages();
    tlv_processing_unique_lock.unlock();

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
 * @brief Wait for the next complete message (indicated by 
 * receiving a magic word) and save the read data into the 
 * serial_message_data_buffer. Times out after 1s of waiting
 * 
 * @return true on successful data capture
 * @return false on error or timeout during data capture
 */
bool SerialStreamer::get_next_serial_frame(void) {
    size_t bytes_transfered = 0;
    boost::system::error_code ec;

    // Set the timeout for the asynchronous read
    timeout.expires_from_now(boost::posix_time::millisec(1000));

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

        // // Print the received response
        // std::cout << "SerialStreamer: Received " << bytes_transfered << " bytes" << std::endl;

        // // if(system_config_reader.verbose){
            
        //     const char* raw_data = boost::asio::buffer_cast<const char*>(serial_stream.data());
        //     size_t raw_data_size = serial_stream.size();
        //     std::cout << "Raw data: ";
        //     for (size_t i = 0; i < raw_data_size; ++i) {
        //         // Print each byte in hex format (uppercase)
        //         std::cout << std::hex << std::uppercase << (0xFF & static_cast<unsigned char>(raw_data[i])) << " ";
        //     }
        //     std::cout << std::dec << std::endl;
        // }

        // Remove the received data from the buffer
        serial_stream.consume(bytes_transfered);

        return true;
    } else if (ec == boost::asio::error::operation_aborted) {
        // Timeout occurred
        std::cout << "SerialStreamer: Timeout while waiting for response" << std::endl;
        // const char* raw_data = boost::asio::buffer_cast<const char*>(serial_stream.data());
        // size_t raw_data_size = serial_stream.size();
        
        // std::cout << "Raw data: ";
        // for (size_t i = 0; i < raw_data_size; ++i) {
        //     // Print each byte in hex format (uppercase)
        //     std::cout << std::hex << std::uppercase << (0xFF & static_cast<unsigned char>(raw_data[i])) << " ";
        // }
        // std::cout << std::dec << std::endl;
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

    header_version = uint32ToHex(header_data[0]);
    header_totalPacketLen = header_data[1];
    header_platform = uint32ToHex(header_data[2]);
    header_frameNumber = header_data[3];
    header_timeCPUCycles = header_data[4];
    header_numDetectedObj = header_data[5];
    header_numTLVs = header_data[6];
    header_subFrameNumber = header_data[7];

    if(system_config_reader.get_verbose()){
        print_status();
    }

    //check to ensure the message is valid
    return check_valid_message();
}

void SerialStreamer::print_status(void){

    std::cout <<
    "frame: " << header_frameNumber << std::endl <<
    "\tversion: " << header_version << std::endl <<
    "\ttotal Packet length: " << header_totalPacketLen << " bytes" << std::endl <<
    "\tplatform: " << header_platform << std::endl <<
    "\ttime (CPU cycles): " << header_timeCPUCycles << std::endl <<
    "\tDetected Objects: " <<header_numDetectedObj << std::endl <<
    "\tNumber of TLVs: " << header_numTLVs <<std::endl <<
    "\tSubframe number: " << header_subFrameNumber << std::endl;
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
    if(static_cast<size_t>(header_totalPacketLen) == 
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
void SerialStreamer::process_TLV_messages(void){

    //start processing after the header
    size_t tlv_start_byte_idx = 32;
    uint32_t TLV_type;
    size_t TLV_len;

    //helper variables for processing tlv packets
    size_t start_idx;
    size_t end_idx;

    for (size_t i = 0; i < header_numTLVs; i++)
    {
        //get the next TLV type and length
        TLV_type = get_TLV_type(tlv_start_byte_idx);
        TLV_len = get_TLV_len(tlv_start_byte_idx);

        //create the tlv_data_vector
        start_idx = tlv_start_byte_idx + 8;
        end_idx = start_idx + TLV_len;
        std::vector<uint8_t> tlv_data(
            serial_message_data_buffer.begin() + start_idx,
            serial_message_data_buffer.begin() + end_idx
        );

        process_TLV(tlv_data,TLV_type);

        //increment the start byte index to process next tlv packet
        tlv_start_byte_idx += TLV_len + 8;
    }
    

}

void SerialStreamer::process_TLV(
    std::vector<uint8_t>  & tlv_data,
    uint32_t tlv_type){

        switch (tlv_type)
        {
        case tlv_codes.DETECTED_POINTS:

            tlv_detected_points_processor.process(
                tlv_data
            );

            VALID_DETECTED_POINTS = tlv_detected_points_processor.valid_data;

            break;
        
        default:
            break;
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