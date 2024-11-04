//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <csignal>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Commands.hpp"
#include "DCA1000Handler.hpp"
#include "DCA1000Runner.hpp"

using json = nlohmann::json;

DCA1000Runner* dca_global = nullptr;

void signalHandler(int signum){
    std::cout << "Interrupt signal (" << signum << ") received.\n";
    if (dca_global && dca_global->initialized) {
        dca_global->stop();
    }
}

int main(int, char**){

    //handle sigint commands
    signal(SIGINT,signalHandler);

    std::string config_file = "../configs/radar_0_IWR1843_demo.json";

    DCA1000Runner dca1000_runner(config_file);
    dca_global = &dca1000_runner;

    if(dca1000_runner.initialized){
        int frame_count = 0;
        int timeout_ms = 2000;

        dca1000_runner.start();

        while(true){
            if(dca1000_runner.get_next_frame(timeout_ms).size() == 0){
                break;
            }else{
                frame_count += 1;
            }
        }

        dca1000_runner.stop();
    }
}
