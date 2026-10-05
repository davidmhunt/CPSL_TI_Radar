//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <csignal>

//JSON handling
#include "Runner.hpp"

using json = nlohmann::json;

Runner* runner_global = nullptr;


void signalHandler(int signum){
    std::cout << "Interrupt signal (" << signum << ") received.\n";
    if (runner_global && runner_global->initialized) {
        runner_global->stop();
    }

    exit(0);
}

int main(int argc, char* argv[]){

    //handle sigint commands
    signal(SIGINT,signalHandler);

    // std::string config_file = "../config/system/radar_0_IWR1843_demo.json";
    // std::string config_file = "../config/system/radar_0_IWR1843_nav_dca_RadSAR_lr.json";
#ifndef DEFAULT_CONFIG_PATH
#define DEFAULT_CONFIG_PATH "../config/system/front_radar_IWR1843_stress_test.json"
#endif
    std::string config_file = DEFAULT_CONFIG_PATH;
    if (argc > 1) {
        config_file = argv[1];
    }
    std::cout << "Using config: " << config_file << std::endl;

    // DCA1000Runner dca1000_runner(config_file);
    Runner runner(config_file);
    runner_global = &runner;

    if(runner.initialized){
        int frame_count = 0;
        int timeout_ms = 2000;

        runner.start();

        while(true){
            bool got_frame = false;

            if(runner.get_dca1000_streaming_enabled() &&
                runner.get_next_adc_cube(timeout_ms).size() > 0){
                got_frame = true;
            }

            if(runner.get_serial_streaming_enabled()){
                std::vector<std::vector<float>> points;
                if(runner.get_next_tlv_detected_points(points, timeout_ms)){
                    got_frame = true;
                    std::cout << "TLV frame " << runner.get_latest_tlv_frame_number()
                              << ": " << points.size() << " detected points";
                    if(!points.empty()){
                        std::cout << " (first: x=" << points[0][0] << " y=" << points[0][1]
                                  << " z=" << points[0][2] << " v=" << points[0][3] << ")";
                    }
                    std::cout << std::endl;
                }
            }

            //stop once no stream produces a frame within the timeout
            if(!got_frame){
                break;
            }
            frame_count += 1;
        }

        if(runner.get_serial_streaming_enabled()){
            std::cout << "Received " << frame_count << " frames, "
                      << runner.get_tlv_missed_frame_count() << " missed" << std::endl;
        }

        runner.stop();
    } else{
        std::cerr << "Runner failed to initialize" << std::endl;
        return 1;
    }

    return 0;
}
