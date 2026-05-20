#ifndef SERIAL_PORT_CONFIG_HPP
#define SERIAL_PORT_CONFIG_HPP

#include <string>
#include <boost/asio.hpp>
#include "RadarConfigReaderDONE.hpp"

class Serial_Port_Config {
public:
    Serial_Port_Config(const std::string& jsonFilePath);
    void run();

private:
    RadarConfigReader m_configReader;
    boost::asio::io_service m_io;
    boost::asio::serial_port m_port;

    void sendCommand(const std::string& command);
};

#endif // SERIAL_PORT_CONFIG_HPP