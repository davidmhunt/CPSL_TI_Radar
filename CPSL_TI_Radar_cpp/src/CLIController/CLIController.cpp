#include"CLIController.hpp"

#include <chrono>
#include <exception>

using namespace std;

/**
 * @brief Default contructor (leaves un-initialized)
 * 
 */
CLIController::CLIController():
    initialized(false),
    stream(nullptr),
    system_config_reader(), //will leave it uninitialized
    io_error_(false)
{}

/**
 * @brief Contructor that initializes the cli_controller
 * 
 * @param systemConfigReader 
 */
CLIController::CLIController(const SystemConfigReader & systemConfigReader):
    initialized(false),
    stream(nullptr),
    system_config_reader(),
    io_error_(false)
{    
    initialize(systemConfigReader);
}

bool CLIController::initialize(const SystemConfigReader & systemConfigReader){

    system_config_reader = systemConfigReader;
    stream.reset();  //closes a port this controller opened before
    io_error_ = false;
    initialized = false;

    if(!system_config_reader.initialized){
        std::cerr << "attempted to initialize cli controller, but system_config_reader was not initialized"
                  << std::endl;
        return false;
    }

    std::string error;
    std::shared_ptr<cpsl::radar::SerialPortStream> port = cpsl::radar::SerialPortStream::open(
        system_config_reader.getRadarCliPort(), system_config_reader.getRadarCliBaudRate(), error);
    if(!port){
        std::cerr << "CLIController: " << error << std::endl;
        return false;
    }
    stream = port;
    initialized = true;
    return initialized;
}

bool CLIController::initialize(const SystemConfigReader & systemConfigReader,
                               std::shared_ptr<cpsl::radar::ByteStream> stream_in){
    system_config_reader = systemConfigReader;
    stream = std::move(stream_in);
    io_error_ = false;
    initialized = system_config_reader.initialized && stream != nullptr;
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
        std::cerr << "attempted to send commands to IWR, but CLI controller isn't initialized" << std::endl;
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
 * @brief Send the sensor stop command. Called on the stop/destructor path:
 * never throws, even when the radar's USB is gone (returns false instead).
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
 * @return error code (std::errc::timed_out on timeout)
 */
std::error_code CLIController::read_until_with_timeout(
    std::string & response,
    const std::string & delim,
    int timeout_ms)
{
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    uint8_t chunk[256];
    while (response.find(delim) == std::string::npos) {
        const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - std::chrono::steady_clock::now());
        if (left.count() <= 0) {
            return std::make_error_code(std::errc::timed_out);
        }
        size_t n = 0;
        std::error_code ec = stream->read_some(chunk, sizeof chunk, n, left);
        if (ec) {
            return ec;
        }
        response.append(reinterpret_cast<const char*>(chunk), n);
    }
    return std::error_code();
}

/**
 * @brief Send a command to the IWR
 * 
 * @param command command to be sent to the board
 * @return true if the board responded with "Done"; false on a timeout, a
 *  missing ack, or an I/O error (which also sets io_error()). Never throws.
 */
bool CLIController::sendCommand(const string& command) {

    if (!stream) {
        cerr << "CLIController: '" << command << "' not sent: no CLI port" << endl;
        return false;
    }

    std::cout << "Sent command: " << command << endl; 

    try {
        //send the command over the serial port
        const string line = command + "\n";
        std::error_code wec = stream->write(reinterpret_cast<const uint8_t*>(line.data()), line.size());
        if (wec) {
            io_error_ = true;
            cerr << "CLIController: write of '" << command << "' failed: " << wec.message() << endl;
            return false;
        }

        //wait to receive confirmation (cli.ack) that the command was accepted
        const cpsl::radar::BoardDescriptor::Cli& cli = system_config_reader.getBoard().cli;
        string resp;
        std::error_code ec = read_until_with_timeout(resp, cli.ack, system_config_reader.getRadarCliTimeoutMs());

        //the board prints its prompt after the ack and drops input while it does
        //(the AM273x cascade demo loses the first characters of the next command),
        //so wait for the prompt before returning. Boards without it just time out.
        if (!ec) {
            std::error_code pec = read_until_with_timeout(resp, cli.prompt, static_cast<int>(cli.prompt_wait_ms));
            if (pec && pec != std::errc::timed_out) {
                io_error_ = true;
                cerr << "CLIController: error while reading the prompt: " << pec.message() << endl;
            }
        }

        //TODO: ONly print the part before the "Done" message
        cout << "Received response: " << resp << endl;

        //handle error codes
        if (ec == std::errc::timed_out) {
            cout << "Timeout while waiting for response. Partial response received." << "\n" << endl;
            return false;
        } else if (ec) {
            io_error_ = true;
            cerr << "Error while reading response: " << ec.message() << "\n" << endl;
            return false;
        } else if (resp.find(cli.ack) == string::npos) {
            cout << "Received partial response. '" << cli.ack << "' message not found." << "\n" << endl;
            return false;
        }
        return true;
    } catch (const std::exception& e) {
        //a ByteStream that throws (e.g. boost::system::system_error after an unplug)
        io_error_ = true;
        cerr << "CLIController: '" << command << "' failed: " << e.what() << endl;
        return false;
    } catch (...) {
        io_error_ = true;
        cerr << "CLIController: '" << command << "' failed with an unknown exception" << endl;
        return false;
    }
}
