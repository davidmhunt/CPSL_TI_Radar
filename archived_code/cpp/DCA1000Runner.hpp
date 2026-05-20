#ifndef DCA1000RUNNER
#define DCA1000RUNNER

// C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <memory>
#include <thread>
#include <mutex>
#include <chrono>
#include <pthread.h> // Include pthread for thread priority adjustments

// CPSLI_TI_RADAR_CPP classes
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Handler.hpp"

/**
 * @brief Class for streaming data from an IWR connected to a DCA1000
 * 
 */
class DCA1000Runner {

// Variables
public:
    bool initialized;
    bool running;
    bool stop_called;

private:
    SystemConfigReader system_config_reader;
    RadarConfigReader radar_config_reader;
    DCA1000Handler dca1000_handler;
    CLIController cli_controller;

    // Mutexes
    std::mutex stop_called_mutex;
    std::mutex running_mutex;

    // Threads
    std::thread run_thread;

    // Helper function to set thread priority
    void set_thread_priority();

public:
    DCA1000Runner();
    DCA1000Runner(const std::string & json_config_file_path);
    ~DCA1000Runner();

    // Initialization
    void initialize(const std::string & json_config_file_path);

    // Stop running
    void start();
    void stop();

    // Wait for and get the next frame
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> get_next_frame(
        int timeout_ms = 100
    );

private:
    void run();
};

#endif