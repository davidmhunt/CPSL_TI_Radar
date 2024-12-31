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
    system_config_reader(), //will leave it uninitialized
    io_context(new boost::asio::io_context()),
    data_port(nullptr),
    serial_stream(),
    timeout(*io_context),
    serial_message_data_buffer(),
    header_data_bytes(32,0),
    header_data(8,0)
{}

/**
 * @brief Construct a new Serial Streamer:: Serial Streamer object
 * 
 * @param systemConfigReader initialized system config reader
 */
SerialStreamer::SerialStreamer(const SystemConfigReader & systemConfigReader):
    initialized(false),
    system_config_reader(),
    io_context(new boost::asio::io_context()),
    data_port(nullptr),
    serial_stream(),
    timeout(*io_context),
    serial_message_data_buffer(),
    header_data_bytes(32,0),
    header_data(8,0)
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
    io_context(rhs.io_context),
    data_port(rhs.data_port),
    system_config_reader(rhs.system_config_reader),
    serial_stream(), // `boost::asio::streambuf` does not support copying; initialize a fresh buffer
    timeout(*rhs.io_context),
    serial_message_data_buffer(rhs.serial_message_data_buffer),
    header_data_bytes(rhs.header_data_bytes),
    header_data(rhs.header_data)
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

bool SerialStreamer::process_next_message(void){

    //get the next serial frame and load it into the serial_message_data_buffer
    if (!get_next_serial_frame()){
        return false;
    }

    //process the header
    if (!process_message_header()){
        return false;
    }

    return true;
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
        [&ec, &bytes_transfered](const boost::system::error_code& e, size_t transfered) {
            ec = e;
            bytes_transfered = transfered;
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

        // Print the received response
        std::cout << "SerialStreamer: Received " << bytes_transfered << " bytes" << std::endl;

        if(system_config_reader.verbose){
            
            const char* raw_data = boost::asio::buffer_cast<const char*>(serial_stream.data());
            size_t raw_data_size = serial_stream.size();
            std::cout << "Raw data: ";
            for (size_t i = 0; i < raw_data_size; ++i) {
                // Print each byte in hex format (uppercase)
                std::cout << std::hex << std::uppercase << (0xFF & static_cast<unsigned char>(raw_data[i])) << " ";
            }
            std::cout << std::dec << std::endl;
        }

        // Remove the received data from the buffer
        serial_stream.consume(bytes_transfered);

        return true;
    } else if (ec == boost::asio::error::operation_aborted) {
        // Timeout occurred
        std::cout << "SerialStreamer: Timeout while waiting for response" << std::endl;
        const char* raw_data = boost::asio::buffer_cast<const char*>(serial_stream.data());
        size_t raw_data_size = serial_stream.size();
        
        std::cout << "Raw data: ";
        for (size_t i = 0; i < raw_data_size; ++i) {
            // Print each byte in hex format (uppercase)
            std::cout << std::hex << std::uppercase << (0xFF & static_cast<unsigned char>(raw_data[i])) << " ";
        }
        std::cout << std::dec << std::endl;
        return false;
    } else {
        // Other errors
        std::cerr << "Error while reading response: " << ec.message() << std::endl;
        return false;
    }
}

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

    //TODO: Do checks to confirm header is operating successfully
    return true;
}

std::string SerialStreamer::uint32ToHex(uint32_t value) {
    std::stringstream ss;
    ss << std::hex << std::uppercase << 
        std::setw(8) << std::setfill('0') 
        << value;
    return ss.str();
}