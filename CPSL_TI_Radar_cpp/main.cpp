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

int main(int, char**){

    //handle sigint commands
    signal(SIGINT,signalHandler);

    // std::string config_file = "../configs/radar_0_IWR1843_demo.json";
    std::string config_file = "../configs/radar_0_IWR1843_nav_dca_RadSAR_lr.json";

    // DCA1000Runner dca1000_runner(config_file);
    Runner runner(config_file);
    runner_global = &runner;

    if(runner.initialized){
        int frame_count = 0;
        int timeout_ms = 2000;

        runner.start();

        while(true){
            if(
                (runner.get_next_adc_cube(timeout_ms).size() == 0)
                && (runner.get_next_tlv_detected_points(timeout_ms).size() == 0)){
                break;
            }else{
                frame_count += 1;
            }
        }

        runner.stop();
    }
}
