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
#include "SerialBaud.hpp"

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

    bool new_frame_available;

    //checking for and accessing latest data
    bool check_new_frame_available();
    std::vector<std::vector<float>> tlv_get_latest_detected_points(void);
    std::vector<std::vector<float>> tlv_get_latest_detected_points_side_info(void);
    uint32_t get_latest_frame_number(void);
    uint32_t get_missed_frame_count(void);

private:

    //mutexes
    std::mutex new_frame_available_mutex;
    std::mutex tlv_processing_mutex;

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

    //header of the frame being parsed (copied to header_* once the frame is valid)
    struct PendingHeader {
        std::string version;
        uint32_t totalPacketLen = 0;
        std::string platform;
        uint32_t frameNumber = 0;
        uint32_t timeCPUCycles = 0;
        uint32_t numDetectedObj = 0;
        uint32_t numTLVs = 0;
        uint32_t subFrameNumber = 0;
    } pending_;

    //frame continuity tracking
    bool have_previous_frame;
    uint32_t previous_frame_number;
    uint32_t missed_frame_count;
    
    //private class functions here
    //processing messages
    bool get_next_serial_frame(void);
    bool process_message_header(void);
    void print_status(void);
    bool check_valid_message(void);

    //functions processing TLVs
    TLVCodes tlv_codes;
    bool process_TLV_messages(void);
    bool process_TLV(
        std::vector<uint8_t> & tlv_data,
        uint32_t tlv_type,
        TLVDetectedPoints & points,
        TLVDetectedPointsSideInfo & side_info);
    void commit_frame(TLVDetectedPoints & points, TLVDetectedPointsSideInfo & side_info);
    uint32_t get_TLV_type(size_t tlv_start_byte_idx);
    size_t get_TLV_len(size_t tlv_start_byte_idx);

    //TLV specific processors
    TLVDetectedPoints tlv_detected_points_processor;
    TLVDetectedPointsSideInfo tlv_side_info_processor;

    //TLV valid data flags
    bool VALID_DETECTED_POINTS;

    //helper functions
    std::string uint32ToHex(uint32_t value);
};

#endif