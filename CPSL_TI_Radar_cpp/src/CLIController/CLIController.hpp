#ifndef CLICONTROLLER
#define CLICONTROLLER

#include <string>
#include <boost/asio.hpp>
#include <iostream>
#include <fstream>
#include <bitset>
#include <memory>
#include "SystemConfigReader.hpp"

class CLIController {
public:
    CLIController();
    CLIController(const SystemConfigReader & systemConfigReader);
    CLIController(const CLIController & rhs);
    CLIController & operator=(const CLIController & rhs);
    ~CLIController();

    bool initialize(const SystemConfigReader & systemConfigReader);

    void send_config_to_IWR();
    void sendStartCommand();
    void sendStopCommand();

    bool initialized;
    
private:

    void sendCommand(const std::string& command);

    std::shared_ptr<boost::asio::io_context> io_context;
    std::shared_ptr<boost::asio::serial_port> cli_port;
    SystemConfigReader system_config_reader;
};

#endif