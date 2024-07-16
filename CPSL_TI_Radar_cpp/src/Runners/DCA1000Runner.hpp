#ifndef DCA1000RUNNER
#define DCA1000RUNNER

//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <memory>
#include <thread>
#include <mutex>
#include <chrono>

//CPSLI_TI_RADAR_CPP classes
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Handler.hpp"

/**
 * @brief Class for streaming data from an IWR connected to a DCA1000
 * 
 */
class DCA1000Runner {

//variables
public:
    bool initialized;
    bool running;
    bool stop_called;

private:
    SystemConfigReader system_config_reader;
    RadarConfigReader radar_config_reader;
    DCA1000Handler dca1000_handler;
    CLIController cli_controller;

    //mutexes
    std::mutex stop_called_mutex;
    std::mutex running_mutex;

    //threads
    std::thread run_thread;

//functions
public:
    DCA1000Runner();
    DCA1000Runner(const std::string & json_config_file_path);
    //NOTE: NOT INCLUDING COPY CONSTRUCTOR TO PREVENT WEIRD BEHAVIOR
    // DCA1000Runner(const DCA1000Runner & rhs);

    //NOTE: NOT INCLUDING ASSIGNMENT OPERATOR TO PREVENT WEIRD BEHAVIOR
    //DCA1000Runner & operator=(const DCA1000Runner & rhs);
    ~DCA1000Runner();

    //initialization
    void initialize(const std::string & json_config_file_path);

    //stop running
    void start();
    void stop();

    //wait for and get the next frame
    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> get_next_frame(
        int timeout_ms = 100
    );

private:
    void run();
};

#endif