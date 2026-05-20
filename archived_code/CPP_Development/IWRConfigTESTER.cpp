#include <iostream>
#include <string>
#include <bitset>
#include <boost/asio.hpp>
#include <fstream>

using namespace std;
using namespace boost::asio;

// Compile with g++ -o readconfig readconfig.cpp -lboost_system -lpthread
// If it says "... is not a valid CLI command" ensure you've flashed the correct firmware on the board

int main() {
    try {
        // Set up serial port
        io_service io;
        serial_port port(io, "/dev/ttyACM0"); // Replace with the correct serial port
        port.set_option(serial_port_base::baud_rate(115200));
        // Open the configuration file

    
     // Read configuration file
    //RadarConfigReader configReader("/path/to/your/json/file.json"); // Replace with the actual JSON file path
    //string configFilePath = configReader.getRadarConfigPath(); 

    //ifstream configFile(configFilePath);
    //if (!configFile) {
     //   cerr << "Failed to open configuration file." << endl;
     //   return 1;
   // }
    
 //   ifstream config_file(configFilePath);
    ifstream config_file("/home/rayhoggard/Documents/CPSL_TI_Radar_CPP/configurations/DCA1000/custom_configs/short_range.cfg");
    //ifstream config_file("/home/rayhoggard/Documents/CPSL_TI_Radar_CPP/configurations/DCA1000/iwr_raw_rosnode/14xx/indoor_human_rcs.cfg");
    //ifstream config_file("/home/rayhoggard/Documents/CPSL_TI_Radar_CPP/configurations/IWR_Demos/1443config.cfg");
    //ifstream config_file("/home/rayhoggard/Documents/CPSL_TI_Radar_CPP/Tests/commands.cfg");
    if (!config_file) {
        cerr << "Failed to open configuration file." << endl;
        return 1;
    }

    // Read and execute commands from the configuration file
    string command;

    while (getline(config_file, command)) {
        // Skip empty lines and comments
        if (command.empty() || command[0] == '#') {
            continue;
        }
        cout << "Sent command: " << command << endl;

        // Add newline
        command += "\n";

         

       /* PRINT BINARY IF NECESSARY
       
        cout << "Sent command (binary): ";
        for (char c : command) {
            cout << bitset<8>(c) << " ";
        }
        cout << endl;

        */

        

        // Send command
        write(port, buffer(command));

        // Wait for response from the radar board with a timeout
        boost::asio::streambuf response;
        boost::system::error_code ec;
        boost::asio::deadline_timer timeout(io);
        timeout.expires_from_now(boost::posix_time::seconds(1)); // Set timeout to 1 second

        async_read_until(port, response, "Done", [&ec](const boost::system::error_code& e, size_t bytes_transferred) {
            ec = e;
        });

        timeout.async_wait([&port](const boost::system::error_code& e) {
            if (!e) {
                // Timeout expired, cancel the read operation
                port.cancel();
            }
        });

        io.run(); // Run the IO service to handle the asynchronous operations
        io.reset(); // Reset the IO service for the next command

        // Get the raw received data
        const char* raw_data = boost::asio::buffer_cast<const char*>(response.data());
        size_t raw_data_size = response.size();

        

       /* PRINT BINARY IF NECESSARY

        cout << "Received response (binary): ";
        for (size_t i = 0; i < raw_data_size; ++i) {
            cout << bitset<8>(static_cast<unsigned char>(raw_data[i])) << " ";
        }
        cout << endl;

        */

        // Convert response to string
        string resp(raw_data, raw_data_size);
        cout << "Received response: " << resp << endl;

        if (ec == boost::asio::error::operation_aborted) {
            // Timeout occurred
            cout << "Timeout while waiting for response. Partial response received." << "\n" << endl;
        } else if (ec) {
            // Other error occurred
            cerr << "Error while reading response: " << ec.message() << "\n" << endl;
            return 1;
        } else {
            // Check if the "Done" message is present in the response
            if (resp.find("Done") != string::npos) {
                cout << "Command executed successfully." << "\n" << endl;
            } else {
                cout << "Received partial response. 'Done' message not found." << "\n" << endl;
            }
        }
    }
}
    catch (exception& e) {
        cerr << "Exception: " << e.what() << "\n" << endl;
        return 1;
    }
    return 0;
}