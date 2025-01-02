#include"CLIController.hpp"

using namespace std;
using namespace boost::asio;

/**
 * @brief Default contructor (leaves un-initialized)
 * 
 */
CLIController::CLIController():
    initialized(false),
    system_config_reader(), //will leave it uninitialized
    io_context(new boost::asio::io_context()),
    cli_port(nullptr)
{}

/**
 * @brief Contructor that initializes the cli_controller
 * 
 * @param systemConfigReader 
 */
CLIController::CLIController(const SystemConfigReader & systemConfigReader):
    initialized(false),
    system_config_reader(),
    io_context(new boost::asio::io_context()),
    cli_port(nullptr)
{    
    initialize(systemConfigReader);
}

/**
 * @brief Copy Contructor
 * 
 * @param rhs 
 */
CLIController::CLIController(const CLIController & rhs):
    initialized(rhs.initialized),
    io_context(rhs.io_context),
    cli_port(rhs.cli_port),
    system_config_reader(rhs.system_config_reader)
{}

CLIController & CLIController::operator=(const CLIController & rhs){
    if(this!= & rhs){

        //close the cli port if it is open
        if(cli_port.get() != nullptr &&
            cli_port.use_count() == 1 && 
            cli_port -> is_open())
        {
            cli_port -> close();
        }

        //copy the other variables over
        initialized = rhs.initialized;
        io_context = rhs.io_context;
        cli_port = rhs.cli_port;
        system_config_reader = rhs.system_config_reader;
    }

    return *this;
}

/**
 * @brief Destroy the CLIController::CLIController object
 * 
 */
CLIController::~CLIController()
{
    //TODO: Check if the serial port is running right now
    if(cli_port.get() != nullptr && 
        cli_port.use_count() == 1 &&
        cli_port -> is_open()){
        cli_port -> close();
    }
}

bool CLIController::initialize(const SystemConfigReader & systemConfigReader){

    system_config_reader = systemConfigReader;

    //check to make sure that the cli port isn't already open
    if(cli_port.get() != nullptr &&
        cli_port.use_count() == 1 && 
        cli_port -> is_open())
    {
        cli_port -> close();
    }

    if(system_config_reader.initialized){
        cli_port = std::make_shared<boost::asio::serial_port>(
            *io_context,system_config_reader.getRadarCliPort());
        cli_port -> set_option(serial_port_base::baud_rate(115200));
        initialized = true;
    } else{
        initialized = false;
        std::cerr << "attempted to initialize cli controller,\
            but system_config_reader was not initialized";
    }

    return initialized;
}

/**
 * @brief Runs the CLI controller, sends all CLI commands in the config file
 * except for the sensorStart command
 * 
 */
void CLIController::send_config_to_IWR() {

    if(initialized){
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
            else if (command.find("sensorStart") == std::string::npos)
            {
                //send all commands except for the start command
                CLIController::sendCommand(command);
            }        
        }
    } else{
        std::cerr << "attempted to send commands to IWR, but CLI controller isn't initialized";
    }
}

/**
 * @brief Send the sensor start command
 * 
 */
void CLIController::sendStartCommand()
{
    CLIController::sendCommand("sensorStart");
}

/**
 * @brief Send the sensor stop command
 * 
 */
void CLIController::sendStopCommand()
{
    CLIController::sendCommand("sensorStop");
}

/**
 * @brief Send a command to the IWR
 * 
 * @param command command to be sent to the board
 */
void CLIController::sendCommand(const string& command) {

    std::cout << "Sent command: " << command << endl; 
    
    //send the command over the serial port
    write(*cli_port, buffer(command + "\n"));

    //wait to receive confirmation that the command was sent
    boost::asio::streambuf response;
    boost::system::error_code ec;
    boost::asio::deadline_timer timeout(*io_context);
    timeout.expires_from_now(boost::posix_time::millisec(100));

    async_read_until(*cli_port, response, "Done", [&ec](const boost::system::error_code& e, size_t bytes_transferred) {
        ec = e;
    });

    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            cli_port -> cancel();
        }
    });

    io_context -> run();
    io_context -> reset();

    const char* raw_data = boost::asio::buffer_cast<const char*>(response.data());
    size_t raw_data_size = response.size();
    //TODO: ONly print the part before the "Done" message
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