#include"CLIController.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>

#include "Log.hpp"

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
        cpsl::radar::log_error("attempted to initialize cli controller, but system_config_reader was not initialized");
        return false;
    }

    std::string error;
    std::shared_ptr<cpsl::radar::SerialPortStream> port = cpsl::radar::SerialPortStream::open(
        system_config_reader.getRadarCliPort(), system_config_reader.getRadarCliBaudRate(), error);
    if(!port){
        cpsl::radar::log_error("CLIController: ", error);
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
            cpsl::radar::log_error("CLIController: failed to open the radar cfg ", configFilePath);
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

        for (const string& skipped : plan.skipped) {
            cpsl::radar::log_debug("Skipped command (board ", system_config_reader.getBoard().name,
                                   " skip_commands): ", skipped);
        }

        //skipped commands are never sent, so they do not count as unacknowledged
        bool all_done = true;
        bool any_io_error = false;
        for (const string& command : plan.send) {
            if(!CLIController::sendCommand(command, system_config_reader.getRadarCliTimeoutMs())){
                all_done = false;
                any_io_error = any_io_error || io_error_;
            }
            //an acknowledged command whose prompt read failed is only a
            //warning (logged by sendCommand), not an I/O error of the cfg
            //(core-13 review S3)
        }
        //for the whole cfg, io_error() says whether a command that failed hit an I/O error
        io_error_ = any_io_error;
        return all_done;
    } else{
        cpsl::radar::log_error("attempted to send commands to IWR, but CLI controller isn't initialized");
        return false;
    }
}

/**
 * @brief Send the sensor start command
 * 
 */
bool CLIController::sendStartCommand()
{
    return CLIController::sendCommand(system_config_reader.getBoard().cli.start_cmd,
                                      system_config_reader.getRadarCliTimeoutMs());
}

/**
 * @brief Send the sensor stop command. Called on the stop/destructor path:
 * never throws, even when the radar's USB is gone (returns false instead).
 * 
 */
bool CLIController::sendStopCommand()
{
    return CLIController::sendCommand(system_config_reader.getBoard().cli.stop_cmd, stop_timeout_ms());
}

int CLIController::stop_timeout_ms() const
{
    const cpsl::radar::BoardDescriptor::Cli& cli = system_config_reader.getBoard().cli;
    if (cli.stop_timeout_ms > 0) {
        return static_cast<int>(cli.stop_timeout_ms);
    }
    const int after_frame = static_cast<int>(std::ceil(frame_period_ms_ > 0.0f ? frame_period_ms_ : 0.0f)) + 200;
    return std::max(static_cast<int>(cli.cmd_timeout_ms), after_frame);
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
bool CLIController::sendCommand(const string& command, int timeout_ms) {

    //io_error() describes this command only (core-11 review S2: it used to stick)
    io_error_ = false;

    if (!stream) {
        cpsl::radar::log_error("CLIController: '", command, "' not sent: no CLI port");
        return false;
    }

    cpsl::radar::log_debug("Sent command: ", command);

    try {
        //send the command over the serial port
        const string line = command + "\n";
        //bounded: a wedged CDC device must not hang the stop path (core-11 review S5)
        std::error_code wec = stream->write(reinterpret_cast<const uint8_t*>(line.data()), line.size(),
                                            std::chrono::milliseconds(timeout_ms));
        if (wec) {
            io_error_ = true;
            cpsl::radar::log_error("CLIController: write of '", command, "' failed: ", wec.message());
            return false;
        }

        //wait to receive confirmation (cli.ack) that the command was accepted
        const cpsl::radar::BoardDescriptor::Cli& cli = system_config_reader.getBoard().cli;
        string resp;
        std::error_code ec = read_until_with_timeout(resp, cli.ack, timeout_ms);

        //the board prints its prompt after the ack and drops input while it does
        //(the AM273x cascade demo loses the first characters of the next command),
        //so wait for the prompt before returning. Boards without it just time out.
        if (!ec) {
            std::error_code pec = read_until_with_timeout(resp, cli.prompt, static_cast<int>(cli.prompt_wait_ms));
            if (pec && pec != std::errc::timed_out) {
                io_error_ = true;
                cpsl::radar::log_warn("CLIController: error while reading the prompt after '", command, "': ",
                                      pec.message());
            }
        }

        cpsl::radar::log_debug("Received response: ", resp);

        //handle error codes
        if (ec == std::errc::timed_out) {
            cpsl::radar::log_warn("CLIController: no '", cli.ack, "' for '", command, "' within ",
                                  timeout_ms, " ms");
            return false;
        } else if (ec) {
            io_error_ = true;
            cpsl::radar::log_error("CLIController: error while reading the response to '", command, "': ",
                                   ec.message());
            return false;
        } else if (resp.find(cli.ack) == string::npos) {
            cpsl::radar::log_debug("Received partial response. '", cli.ack, "' message not found.");
            return false;
        }
        return true;
    } catch (const std::exception& e) {
        //a ByteStream that throws (e.g. std::system_error after an unplug)
        io_error_ = true;
        cpsl::radar::log_error("CLIController: '", command, "' failed: ", e.what());
        return false;
    } catch (...) {
        io_error_ = true;
        cpsl::radar::log_error("CLIController: '", command, "' failed with an unknown exception");
        return false;
    }
}
