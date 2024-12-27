#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <iostream>
#include <fstream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <vector>
#include <endian.h>
#include <complex>
#include <memory>
#include <mutex>

#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "DCA1000Commands.hpp"


class DCA1000Handler {
//variables
public:
    //initialization status
    bool initialized;

    bool new_frame_available;

private:

    //mutexes
    std::mutex new_frame_available_mutex;
    std::mutex adc_data_cube_mutex;

    //system configuration information
    SystemConfigReader system_config_reader;

    //radar configuration information
    RadarConfigReader radar_config_reader;

    //connection information
    std::string DCA_fpgaIP;
    std::string DCA_systemIP;
    int DCA_cmdPort;
    int DCA_dataPort;

    //command and data sockets
    std::shared_ptr<int> cmd_socket;
    std::shared_ptr<int> data_socket;

    //addresses
    sockaddr_in cmd_address;
    sockaddr_in data_address;

    //processing udp data packets
    std::vector<uint8_t> udp_packet_buffer;
    size_t udp_packet_size;
    std::uint32_t dropped_packets;
    std::uint32_t dropped_packet_events;
    std::uint32_t received_packets;
    std::uint64_t adc_data_byte_count;

    //assembling frames
    std::vector<uint8_t> frame_byte_buffer; //for assembling new frame byte buffers
    std::uint32_t received_frames;
    std::uint64_t next_frame_byte_buffer_idx;
    std::uint64_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;
    size_t num_rx_channels;

    //saving to a file
    bool save_to_file;
    std::shared_ptr<std::ofstream> out_file;
    
    //assembling the adc data cube
    //NOTE: indexed by [Rx channel, sample, chirp]

    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> adc_data_cube;

    //processing completed frames
    std::vector<uint8_t> latest_frame_byte_buffer; //most recently capture complete frame byte buffer

//functions
public:
    DCA1000Handler();
    DCA1000Handler( const SystemConfigReader& configReader,
                    const RadarConfigReader& radarConfigReader);
    DCA1000Handler(const DCA1000Handler & rhs);
    DCA1000Handler & operator=(const DCA1000Handler & rhs);
    ~DCA1000Handler();

    bool initialize(const SystemConfigReader& configReader,
                    const RadarConfigReader& radarConfigReader);

    //commands to the DCA1000
    bool send_resetFPGA(); //2nd command
    bool send_recordStart(); 
    bool send_recordStop();
    bool send_systemConnect(); //1st command
    bool send_configPacketData(size_t packet_size = 1472, uint16_t delay_us = 25);
    bool send_configFPGAGen();
    float send_readFPGAVersion(); //5th command

    //processing/receiving packets
    bool process_next_packet();

    //checking for new frame availability
    bool check_new_frame_available();
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> get_latest_adc_cube();

private:

    //additional initialization steps
    void load_config();
    void init_addresses();
    bool init_sockets();
    bool configure_DCA1000();
    bool sendCommand(std::vector<uint8_t>& command);
    bool receiveResponse(std::vector<uint8_t>& buffer);    

    //receiving data / initializing buffers
    void init_buffers();
    ssize_t get_next_udp_packets(std::vector<uint8_t>&buffer);
    void print_status();

    //unpacking packets
    uint32_t get_packet_sequence_number(std::vector<uint8_t>& buffer);
    uint64_t get_packet_byte_count(std::vector<uint8_t>& buffer);
    
    //processing frame byte buffer
    void zero_pad_frame_byte_buffer(std::uint64_t packet_byte_count);
    void save_frame_byte_buffer(bool print_system_status = true);

    //getting the latest adc data cube
    std::vector<std::int16_t> convert_from_bytes_to_ints(
        std::vector<uint8_t>& in_vector);
    std::vector<std::vector<std::int16_t>> reshape_to_2D(
        std::vector<std::int16_t>& in_vector,
        size_t num_rows);
    void update_latest_adc_cube_1443(void);
    void update_latest_adc_cube_1843(void);

    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> get_latest_adc_data_cube(void);

    //handling files
    bool init_out_file();
    void write_adc_data_cube_to_file();
    void write_vector_to_file(std::vector<std::int16_t> &vector);
};

#endif // DCA1000_H