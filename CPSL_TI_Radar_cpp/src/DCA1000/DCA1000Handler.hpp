#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <iostream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <vector>
#include <endian.h>

#include "SystemConfigReader.hpp"
#include "DCA1000Commands.hpp"


class DCA1000Handler {
public:
    DCA1000Handler(const SystemConfigReader& configReader);
    ~DCA1000Handler();

    bool initialize();
    void init_addresses();
    bool init_sockets();
    bool sendCommand(std::vector<uint8_t>& command);
    bool receiveResponse(std::vector<uint8_t>& buffer);

    //commands to the DCA1000
    bool send_resetFPGA(); //2nd command
    bool send_recordStart(); 
    bool send_recordStop();
    bool send_systemConnect(); //1st command
    bool send_configPacketData(size_t packet_size = 1472, uint16_t delay_us = 25);
    bool send_configFPGAGen();
    float send_readFPGAVersion(); //5th command

    //receive data
    void init_buffers(size_t _bytes_per_frame, size_t _samples_per_chirp, size_t _chirps_per_frame);
    bool process_next_packet();
    bool get_next_udp_packets(std::vector<uint8_t>&buffer);
    bool flush_data_buffer();
    void print_status();

private:
    //connection information
    std::string DCA_fpgaIP;
    std::string DCA_systemIP;
    int DCA_cmdPort;
    int DCA_dataPort;

    //command and data sockets
    int cmd_socket;
    int data_socket;

    //addresses
    sockaddr_in cmd_address;
    sockaddr_in data_address;

    //processing udp data packets
    std::vector<uint8_t> udp_packet_buffer;
    size_t udp_packet_size;
    std::uint32_t dropped_packets;
    std::uint32_t received_packets;
    std::uint32_t sequence_number;
    std::uint64_t byte_count;

    //assembling frames
    std::vector<uint8_t> frame_byte_buffer;
    size_t received_frames;
    size_t next_frame_byte_buffer_idx;
    size_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;

    //unpacking packets
    uint32_t get_packet_sequence_number(std::vector<uint8_t>& buffer);
    uint64_t get_packet_byte_count(std::vector<uint8_t>& buffer);
};

#endif // DCA1000_H