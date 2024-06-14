#ifndef CLICONTROLLER
#define CLICONTROLLER

#include <iostream>
#include <cstdlib>
#include <string>

#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace CLIController_namespace {

    class CLIController{

        private:

            std::string json_config_file;
        
        public:

            CLIController(){}
    };

}

#endif