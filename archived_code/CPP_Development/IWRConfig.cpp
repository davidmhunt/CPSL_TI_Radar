#include "IWRConfig.hpp"
#include <iostream>
#include <fstream>
#include <bitset>
#include <boost/asio.hpp>

using namespace std;
using namespace boost::asio;

Serial_Port_Config::Serial_Port_Config(const string& jsonFilePath)
    : m_configReader(jsonFilePath),
      m_port(m_io, m_configReader.getCliPort()) {
    m_port.set_option(serial_port_base::baud_rate(115200));
}

void Serial_Port_Config::run() {
    string configFilePath = m_configReader.getRadarConfigPath();
    ifstream configFile(configFilePath);
    if (!configFile) {
        cerr << "Failed to open configuration file." << endl;
        return;
    }

    string command;
    while (getline(configFile, command)) {
        if (command.empty() || command[0] == '#' || command[0] == '%') {
            continue;
        }
        sendCommand(command);
    }
}

void Serial_Port_Config::sendCommand(const string& command) {
    cout << "Sent command: " << command << endl;
    write(m_port, buffer(command + "\n"));

    boost::asio::streambuf response;
    boost::system::error_code ec;
    boost::asio::deadline_timer timeout(m_io);
    timeout.expires_from_now(boost::posix_time::seconds(1));

    async_read_until(m_port, response, "Done", [&ec](const boost::system::error_code& e, size_t bytes_transferred) {
        ec = e;
    });

    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            m_port.cancel();
        }
    });

    m_io.run();
    m_io.reset();

    const char* raw_data = boost::asio::buffer_cast<const char*>(response.data());
    size_t raw_data_size = response.size();

    string resp(raw_data, raw_data_size);
    cout << "Received response: " << resp << endl;

    if (ec == boost::asio::error::operation_aborted) {
        cout << "Timeout while waiting for response. Partial response received." << "\n" << endl;
    } else if (ec) {
        cerr << "Error while reading response: " << ec.message() << "\n" << endl;
        return;
    } else {
        if (resp.find("Done") != string::npos) {
            cout << "Command executed successfully." << "\n" << endl;
        } else {
            cout << "Received partial response. 'Done' message not found." << "\n" << endl;
        }
    }
}