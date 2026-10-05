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
#include <functional>

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

    //guards adc_data_cube and new_frame_available together (published as one)
    std::mutex frame_mutex;

    //tests only: runs after a frame is converted, before it is published
    std::function<void()> publish_hook_;

    bool output_files_ok_ = true;

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
    size_t udp_packet_size;

    //frame tracking (packet/drop stats are owned by assembler_)
    std::uint32_t received_frames;
    std::uint64_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;
    size_t num_rx_channels;

    //saving to files (output.save_adc_frames / output.save_raw_lvds)
    bool save_adc_frames;
    bool save_raw_lvds;
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

    //configs, output files and frame buffers only: no socket, no DCA1000
    //commands (initialize() starts with it; hardware-free tests use it alone)
    bool configure_pipeline(const SystemConfigReader& configReader,
                            const RadarConfigReader& radarConfigReader);

    //assemble one raw DCA1000 UDP packet (what process_next_packet() pops)
    void ingest_packet(const uint8_t* data, int len);

    //tests only: called between converting a frame and publishing it
    void set_publish_hook(std::function<void()> hook);

    //end of a capture: stop the RX thread, send recordStop if the DCA1000 was
    //initialized, then flush and close the output files. Call it after the
    //thread running process_next_packet() has been joined. Idempotent; never throws.
    //Returns false if recordStop was not acknowledged or a file failed to flush.
    bool stop();
    //false if flushing/closing an output file failed in stop()
    bool output_files_ok() const { return output_files_ok_; }

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
    bool close_output_files();
};

#endif // DCA1000_H