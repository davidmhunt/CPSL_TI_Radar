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
        initialized = set_serial_baud_rate(*cli_port, system_config_reader.getRadarCliBaudRate());
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
 * @return true if every command was acknowledged with "Done"
 * @return false if the file couldn't be opened or any command failed/timed out
 */
bool CLIController::send_config_to_IWR() {

    if(initialized){
        //get the configuration file path
        string configFilePath = system_config_reader.getRadarConfigPath();
        ifstream configFile(configFilePath);

        //if the configuration file isn't found
        if (!configFile) {
            cerr << "Failed to open configuration file." << endl;
            return false;
        }

        //read the cfg, then let the board descriptor decide what is sent:
        //comments (cli.skip_prefixes) and the start command are dropped, and
        //cfg_dialect.skip_commands (e.g. calibData on the IWR1843) are skipped
        std::vector<std::string> lines;
        string line;
        while (getline(configFile, line)) {
            lines.push_back(line);
        }
        const cpsl::radar::CfgCommandPlan plan =
            cpsl::radar::filter_cfg_commands(lines, system_config_reader.getBoard());

        if(system_config_reader.get_verbose()){
            for (const string& skipped : plan.skipped) {
                cout << "Skipped command (board " << system_config_reader.getBoard().name
                     << " skip_commands): " << skipped << endl;
            }
        }

        //skipped commands are never sent, so they do not count as unacknowledged
        bool all_done = true;
        for (const string& command : plan.send) {
            if(!CLIController::sendCommand(command)){
                all_done = false;
            }
        }
        return all_done;
    } else{
        std::cerr << "attempted to send commands to IWR, but CLI controller isn't initialized";
        return false;
    }
}

/**
 * @brief Send the sensor start command
 * 
 */
bool CLIController::sendStartCommand()
{
    return CLIController::sendCommand(system_config_reader.getBoard().cli.start_cmd);
}

/**
 * @brief Send the sensor stop command
 * 
 */
bool CLIController::sendStopCommand()
{
    return CLIController::sendCommand(system_config_reader.getBoard().cli.stop_cmd);
}

/**
 * @brief Read from the CLI port until delim is in the buffer or timeout_ms passes
 *
 * @param response buffer to append to (may already hold data read past an earlier delimiter)
 * @param delim string to wait for
 * @param timeout_ms how long to wait
 * @return error code (operation_aborted on timeout)
 */
boost::system::error_code CLIController::read_until_with_timeout(
    boost::asio::streambuf & response,
    const std::string & delim,
    int timeout_ms)
{
    boost::system::error_code ec;
    boost::asio::deadline_timer timeout(*io_context);
    timeout.expires_from_now(boost::posix_time::millisec(timeout_ms));

    async_read_until(*cli_port, response, delim, [&ec, &timeout](const boost::system::error_code& e, size_t) {
        ec = e;

        //stop waiting as soon as delim arrives instead of running out the timer
        if (!e) {
            boost::system::error_code cancel_ec;
            timeout.cancel(cancel_ec);
        }
    });

    timeout.async_wait([this](const boost::system::error_code& e) {
        if (!e) {
            cli_port -> cancel();
        }
    });

    io_context -> run();
    io_context -> reset();

    return ec;
}

/**
 * @brief Send a command to the IWR
 * 
 * @param command command to be sent to the board
 * @return true if the board responded with "Done"
 */
bool CLIController::sendCommand(const string& command) {

    std::cout << "Sent command: " << command << endl; 
    
    //send the command over the serial port
    write(*cli_port, buffer(command + "\n"));

    //wait to receive confirmation (cli.ack) that the command was accepted
    const cpsl::radar::BoardDescriptor::Cli& cli = system_config_reader.getBoard().cli;
    boost::asio::streambuf response;
    boost::system::error_code ec = read_until_with_timeout(
        response, cli.ack, system_config_reader.getRadarCliTimeoutMs());

    //the board prints its prompt after the ack and drops input while it does
    //(the AM273x cascade demo loses the first characters of the next command),
    //so wait for the prompt before returning. Boards without it just time out.
    if (!ec) {
        read_until_with_timeout(response, cli.prompt, static_cast<int>(cli.prompt_wait_ms));
    }

    const char* raw_data = boost::asio::buffer_cast<const char*>(response.data());
    size_t raw_data_size = response.size();
    //TODO: ONly print the part before the "Done" message
    string resp(raw_data, raw_data_size);
    cout << "Received response: " << resp << endl;

    //handle error codes
    if (ec == boost::asio::error::operation_aborted) {
        cout << "Timeout while waiting for response. Partial response received." << "\n" << endl;
        return false;
    } else if (ec) {
        cerr << "Error while reading response: " << ec.message() << "\n" << endl;
        return false;
    } else {
        if (resp.find(cli.ack) == string::npos) {
            cout << "Received partial response. '" << cli.ack << "' message not found." << "\n" << endl;
            return false;
        }
    }
    return true;
}