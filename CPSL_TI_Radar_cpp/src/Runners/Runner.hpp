#ifndef RUNNER
#define RUNNER

//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <memory>
#include <thread>
#include <mutex>
#include <chrono>
#include <pthread.h> // Include pthread for thread priority adjustments


//CPSLI_TI_RADAR_CPP classes
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Handler.hpp"
#include "SerialStreamer.hpp"

/**
 * @brief Class for streaming data from an IWR connected to a DCA1000
 * 
 */
class Runner {

//variables
public:
    bool initialized;

private:
    bool running_dca1000;
    bool running_serial;
    bool stop_called;

    SystemConfigReader system_config_reader;
    RadarConfigReader radar_config_reader;
    DCA1000Handler dca1000_handler;
    CLIController cli_controller;
    SerialStreamer serial_streamer;

    //mutexes
    std::mutex stop_called_mutex;
    std::mutex running_dca1000_mutex;
    std::mutex running_serial_mutex;

    //threads
    std::thread run_thread_dca1000;
    std::thread run_thread_serial;

//functions
public:
    Runner();
    Runner(const std::string & json_config_file_path);
    //NOTE: NOT INCLUDING COPY CONSTRUCTOR TO PREVENT WEIRD BEHAVIOR
    // Runner(const Runner & rhs);

    //NOTE: NOT INCLUDING ASSIGNMENT OPERATOR TO PREVENT WEIRD BEHAVIOR
    //Runner & operator=(const Runner & rhs);
    ~Runner();

    //initialization
    void initialize(const std::string & json_config_file_path);

    //stop running
    void start();
    void start_dca1000();
    void start_serial();
    void stop();

    //wait for and get the next frame
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> get_next_adc_cube(
        int timeout_ms = 100
    );
    std::vector<std::vector<float>> get_next_tlv_detected_points(
        int timeout_ms = 100
    );

    //get information for downstream tasks
    bool get_serial_streaming_enabled(void);
    bool get_dca1000_streaming_enabled(void);
    std::string get_radar_config_path(void) const;

private:
    void run_dca1000();
    void run_serial();

    // Helper function to set thread priority
    void set_thread_priority();
};

#endif