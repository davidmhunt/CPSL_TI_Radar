#ifndef SERIALSTREAMER
#define SERIALSTREAMER

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <algorithm>
#include <boost/asio.hpp>
#include <iostream>
#include <fstream>
#include <bitset>
#include <memory>
#include <endian.h>

#include "SystemConfigReader.hpp"
#include "TLVProcessing.hpp"

class SerialStreamer {

public:
    SerialStreamer();
    SerialStreamer(const SystemConfigReader & systemConfigReader);
    SerialStreamer(const SerialStreamer & rhs);
    SerialStreamer & operator=(const SerialStreamer & rhs);
    ~SerialStreamer();

    bool initialize(const SystemConfigReader & systemConfigReader);

    //add public class functions here
    bool process_next_message(void);

    //add public class variables here
    bool initialized;
    const std::string magic_word = "\x02\x01\x04\x03\x06\x05\x08\x07";

private:
    //private class variables here
    SystemConfigReader system_config_reader;
    std::shared_ptr<boost::asio::io_context> io_context;
    std::shared_ptr<boost::asio::serial_port> data_port;
    boost::asio::streambuf serial_stream;
    boost::asio::deadline_timer timeout;


    //data vectors for receiving and processing serial data
    std::vector<uint8_t> serial_message_data_buffer;
    std::vector<uint8_t> header_data_bytes;
    std::vector<uint32_t> header_data;

    //header data
    std::string header_version;
    uint32_t header_totalPacketLen;
    std::string header_platform;
    uint32_t header_frameNumber;
    uint32_t header_timeCPUCycles;
    uint32_t header_numDetectedObj;
    uint32_t header_numTLVs;
    uint32_t header_subFrameNumber;
    
    //private class functions here
    //processing messages
    bool get_next_serial_frame(void);
    bool process_message_header(void);
    void print_status(void);
    bool check_valid_message(void);

    //functions processing TLVs
    TLVCodes tlv_codes;
    void process_TLV_messages(void);
    void process_TLV(
        std::vector<uint8_t> & tlv_data,
        uint32_t tlv_type);
    uint32_t get_TLV_type(size_t tlv_start_byte_idx);
    size_t get_TLV_len(size_t tlv_start_byte_idx);

    //TLV specific processors
    TLVDetectedPoints tlv_detected_points_processor;

    //TLV valid data flags
    bool VALID_DETECTED_POINTS;

    //helper functions
    std::string uint32ToHex(uint32_t value);
};

#endif