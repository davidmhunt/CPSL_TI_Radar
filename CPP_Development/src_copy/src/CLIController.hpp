#ifndef CLICONTROLLER
#define CLICONTROLLER

#include <string>
#include <boost/asio.hpp>
#include <iostream>
#include <fstream>
#include <bitset>
#include "SystemConfigReader.hpp"

class CLIController {
public:
    CLIController(const std::string& jsonFilePath);
    void run();
    void sendStartCommand();
    void sendStopCommand();

private:
    SystemConfigReader system_config_reader;
    boost::asio::io_context io_context;
    boost::asio::serial_port cli_port;

    void sendCommand(const std::string& command);
};

#endif