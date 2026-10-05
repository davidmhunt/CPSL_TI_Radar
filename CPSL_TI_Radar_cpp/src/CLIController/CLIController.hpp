#ifndef CLICONTROLLER
#define CLICONTROLLER

#include <string>
#include <boost/asio.hpp>
#include <iostream>
#include <fstream>
#include <bitset>
#include <memory>
#include "SystemConfigReader.hpp"
#include "SerialBaud.hpp"

class CLIController {
public:
    CLIController();
    CLIController(const SystemConfigReader & systemConfigReader);
    CLIController(const CLIController & rhs);
    CLIController & operator=(const CLIController & rhs);
    ~CLIController();

    bool initialize(const SystemConfigReader & systemConfigReader);

    bool send_config_to_IWR();
    bool sendStartCommand();
    bool sendStopCommand();

    bool initialized;
    
private:

    bool sendCommand(const std::string& command);
    boost::system::error_code read_until_with_timeout(
        boost::asio::streambuf & response,
        const std::string & delim,
        int timeout_ms);

    std::shared_ptr<boost::asio::io_context> io_context;
    std::shared_ptr<boost::asio::serial_port> cli_port;
    SystemConfigReader system_config_reader;
};

#endif