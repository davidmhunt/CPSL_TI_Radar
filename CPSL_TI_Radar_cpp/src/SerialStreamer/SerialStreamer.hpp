#ifndef SERIALSTREAMER
#define SERIALSTREAMER

#include <string>
#include <boost/asio.hpp>
#include <iostream>
#include <fstream>
#include <bitset>
#include <memory>
#include "SystemConfigReader.hpp"

class SerialStreamer {

public:
    SerialStreamer();
    SerialStreamer(const SystemConfigReader & systemConfigReader);
    SerialStreamer(const SerialStreamer & rhs);
    SerialStreamer & operator=(const SerialStreamer & rhs);
    ~SerialStreamer();

    bool initialize(const SystemConfigReader & systemConfigReader);

    //add public class functions here
    bool process_next_packet(void);
    bool get_next_serial_frame(void);

    //add public class variables here
    bool initialized;
    const std::string magic_word = "\x02\x01\x04\x03\x06\x05\x08\x07";

private:
    //private class variables here
    std::shared_ptr<boost::asio::io_context> io_context;
    std::shared_ptr<boost::asio::serial_port> data_port;
    boost::asio::streambuf serial_stream;
    boost::asio::deadline_timer timeout;
    SystemConfigReader system_config_reader;

    //data vectors for receiving serial data
    std::vector<uint8_t> serial_data_buffer;

    //private class functions here
};

#endif