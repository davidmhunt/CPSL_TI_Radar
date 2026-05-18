#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <iostream>
#include <fstream>
#include <vector>
#include <complex>
#include <memory>
#include <mutex>

#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "DCA1000Commands.hpp"
#include "ADCCubeConverter.hpp"
#include "FrameAssembler.hpp"
#include "DCA1000Socket.hpp"


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

    //UDP socket management + dedicated RX thread + ring buffer
    DCA1000Socket socket_;

    //processing udp data packets
    std::vector<uint8_t> udp_packet_buffer;
    size_t udp_packet_size;

    //frame tracking (packet/drop stats are owned by assembler_)
    std::uint32_t received_frames;
    std::uint64_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;
    size_t num_rx_channels;

    //saving to a file
    bool save_to_file;
    std::shared_ptr<std::ofstream> adc_cube_out_file;
    std::shared_ptr<std::ofstream> raw_lvds_out_file;
    
    //assembling the adc data cube
    //NOTE: indexed by [Rx channel, sample, chirp]
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> adc_data_cube;

    //ADC cube conversion (interleaved / non-interleaved)
    ADCCubeConverter converter_;

    //frame assembly (sequence checking, drop detection, frame buffering)
    FrameAssembler assembler_;

    //processing completed frames
    std::vector<uint8_t> latest_frame_byte_buffer; //most recently captured complete frame byte buffer

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
    bool init_sockets();
    bool configure_DCA1000();

    //receiving data / initializing buffers
    void init_buffers();
    void print_status();

    //processing frame byte buffer
    void save_frame_byte_buffer(bool print_system_status = true);

    //handling files
    bool init_out_file();
    void write_adc_data_cube_to_file();
    void write_vector_to_file(std::vector<std::int16_t> &vector);
};

#endif // DCA1000_H