#include"CLIController.hpp"

using namespace std;
using namespace boost::asio;

CLIController::CLIController(const string& jsonFilePath):
    system_config_reader(jsonFilePath),
    cli_port(io_context, system_config_reader.getRadarCliPort()) 
{
    cli_port.set_option(serial_port_base::baud_rate(115200));
}

void CLIController::run() {

    //get the configuration file path
    string configFilePath = system_config_reader.getRadarConfigPath();
    ifstream configFile(configFilePath);

    //if the configuration file isn't found
    if (!configFile) {
        cerr << "Failed to open configuration file." << endl;
        return;
    }

    //if the file is found, send it to the device
    string command;
    while (getline(configFile, command)) {

        //skip comments
        if (command.empty() || command[0] == '#' || command[0] == '%') {
            continue;
        }

        //send the command
        sendCommand(command);
    }
}

void CLIController::sendCommand(const string& command) {

    std::cout << "Sent command: " << command << endl; 
    
    //send the command over the serial port
    write(cli_port, buffer(command + "\n"));

    //wait to receive confirmation that the command was sent
    boost::asio::streambuf response;
    boost::system::error_code ec;
    boost::asio::deadline_timer timeout(io_context);
    timeout.expires_from_now(boost::posix_time::millisec(50));

    async_read_until(cli_port, response, "Done", [&ec](const boost::system::error_code& e, size_t bytes_transferred) {
        ec = e;
    });

    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            cli_port.cancel();
        }
    });

    io_context.run();
    io_context.reset();

    const char* raw_data = boost::asio::buffer_cast<const char*>(response.data());
    size_t raw_data_size = response.size();

    string resp(raw_data, raw_data_size);
    cout << "Received response: " << resp << endl;

    //handle error codes
    if (ec == boost::asio::error::operation_aborted) {
        cout << "Timeout while waiting for response. Partial response received." << "\n" << endl;
    } else if (ec) {
        cerr << "Error while reading response: " << ec.message() << "\n" << endl;
        return;
    } else {
        if (resp.find("Done") == string::npos) {
            cout << "Received partial response. 'Done' message not found." << "\n" << endl;
        }
    }
}