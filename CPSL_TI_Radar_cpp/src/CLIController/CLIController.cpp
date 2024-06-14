#include"CLIController.hpp"

using namespace std;
using namespace boost::asio;

CLIController::CLIController(const string& jsonFilePath)
    : system_config_reader(jsonFilePath),
      cli_port(io_service, system_config_reader.getRadarCliPort()) {
    cli_port.set_option(serial_port_base::baud_rate(115200));
}

void CLIController::run() {
    string configFilePath = system_config_reader.getRadarConfigPath();
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

void CLIController::sendCommand(const string& command) {
    cout << "Sent command: " << command << endl;
    write(cli_port, buffer(command + "\n"));

    boost::asio::streambuf response;
    boost::system::error_code ec;
    boost::asio::deadline_timer timeout(io_service);
    timeout.expires_from_now(boost::posix_time::seconds(1));

    async_read_until(cli_port, response, "Done", [&ec](const boost::system::error_code& e, size_t bytes_transferred) {
        ec = e;
    });

    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            cli_port.cancel();
        }
    });

    io_service.run();
    io_service.reset();

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