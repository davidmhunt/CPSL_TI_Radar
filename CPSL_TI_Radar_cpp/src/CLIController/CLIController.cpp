#include"CLIController.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>

#include "Log.hpp"

using namespace std;

namespace {

//The reply text of one command for the cli echo line: the echoed command, the
//ack ("Done") and the prompt are dropped, \r removed, the remaining lines
//joined with " | " and the result capped at 200 chars. The GUI parses the
//echo line (radar_gui/driver.py); see docs/ARCHITECTURE.md.
string echo_reply(const string& resp, const string& command, const string& ack, const string& prompt) {
    auto trim = [](string t) {
        const char* ws = " \t\r\n";
        const size_t b = t.find_first_not_of(ws);
        if (b == string::npos) return string();
        return t.substr(b, t.find_last_not_of(ws) - b + 1);
    };
    string out;
    size_t pos = 0;
    while (pos <= resp.size()) {
        size_t nl = resp.find('\n', pos);
        if (nl == string::npos) nl = resp.size();
        string ln = trim(resp.substr(pos, nl - pos));
        pos = nl + 1;
        if (ln.empty() || ln == trim(command) || ln == trim(ack)) continue;
        if (!prompt.empty()) {
            //drop the prompt, also when it trails a reply on the same line
            const size_t at = ln.find(prompt);
            if (at != string::npos) {
                //the prompt is "<name>:/>" and the board prints the name before
                //it (mmwDemo:/>): drop that trailing word too
                ln = ln.substr(0, at);
                const size_t sp = ln.find_last_of(" \t");
                ln = trim(sp == string::npos ? string() : ln.substr(0, sp));
            }
            if (ln.empty()) continue;
        }
        if (!out.empty()) out += " | ";
        out += ln;
    }
    for (char& c : out) {
        if (c == '"') c = '\'';
    }
    if (out.size() > 200) out = out.substr(0, 200) + "...";
    return out;
}

}  // namespace

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
            cpsl::radar::log_info("cli [skip] ", skipped, " (skip_commands)");
        }

        //skipped commands are never sent, so they do not count as unacknowledged
        bool all_done = true;
        bool any_io_error = false;
        size_t index = 0;
        for (const string& command : plan.send) {
            ++index;
            const string tag = to_string(index) + "/" + to_string(plan.send.size());
            if(!CLIController::sendCommand(command, system_config_reader.getRadarCliTimeoutMs(), tag)){
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
                                      system_config_reader.getRadarCliTimeoutMs(), "start");
}

/**
 * @brief Send the sensor stop command. Called on the stop/destructor path:
 * never throws, even when the radar's USB is gone (returns false instead).
 * 
 */
bool CLIController::sendStopCommand()
{
    return CLIController::sendCommand(system_config_reader.getBoard().cli.stop_cmd, stop_timeout_ms(), "stop");
}

std::string CLIController::query(const std::string& command, int timeout_ms)
{
    io_error_ = false;
    if (!stream) {
        cpsl::radar::log_error("CLIController: '", command, "' not sent: no CLI port");
        return std::string();
    }
    const auto t_start = std::chrono::steady_clock::now();
    const std::string tag = "id";
    try {
        const string line = command + "\n";
        std::error_code wec = stream->write(reinterpret_cast<const uint8_t*>(line.data()), line.size(),
                                            std::chrono::milliseconds(timeout_ms));
        if (wec) {
            io_error_ = true;
            cpsl::radar::log_error("CLIController: write of '", command, "' failed: ", wec.message());
            return std::string();
        }
        const cpsl::radar::BoardDescriptor::Cli& cli = system_config_reader.getBoard().cli;
        string resp;
        std::error_code ec;
        bool acked = false;
        std::chrono::steady_clock::time_point ack_at;
        const auto deadline = t_start + std::chrono::milliseconds(timeout_ms);
        uint8_t chunk[256];
        for (;;) {
            //done: the prompt follows the command echo (an unrecognised command gets no ack), or the
            //ack and then the prompt (no echo), or the ack on a board without a prompt
            const size_t echo = resp.find(command);
            const size_t after = echo == string::npos ? string::npos : echo + command.size();
            if (!cli.prompt.empty() && after != string::npos && resp.find(cli.prompt, after) != string::npos) break;
            const size_t ack_pos = resp.find(cli.ack);
            if (ack_pos != string::npos) {
                if (!acked) { acked = true; ack_at = std::chrono::steady_clock::now(); }
                if (cli.prompt.empty() || resp.find(cli.prompt, ack_pos) != string::npos) break;
                if (std::chrono::steady_clock::now() - ack_at >= std::chrono::milliseconds(cli.prompt_wait_ms)) break;
            }
            const auto now = std::chrono::steady_clock::now();
            if (now >= deadline) { ec = std::make_error_code(std::errc::timed_out); break; }
            size_t n = 0;
            ec = stream->read_some(chunk, sizeof chunk, n,
                                   std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now));
            if (ec == std::errc::timed_out) { ec.clear(); continue; }   //re-check the deadline above
            if (ec) break;
            resp.append(reinterpret_cast<const char*>(chunk), n);
        }
        const long long elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t_start).count();
        if (ec && ec != std::errc::timed_out) {
            io_error_ = true;
            cpsl::radar::log_error("CLIController: error while reading the response to '", command, "': ",
                                   ec.message());
            return std::string();
        }
        const bool got_ack = resp.find(cli.ack) != string::npos;
        const string reply = echo_reply(resp, command, cli.ack, cli.prompt);
        const string quoted = reply.empty() ? string() : " \"" + reply + "\"";
        if (got_ack) {
            cpsl::radar::log_info("cli [", tag, "] ", command, " -> DONE (", elapsed_ms, " ms)", quoted);
        } else if (reply.find("Error") != string::npos || reply.find("not recognized") != string::npos) {
            cpsl::radar::log_info("cli [", tag, "] ", command, " -> ERROR (", elapsed_ms, " ms)", quoted);
        } else {
            cpsl::radar::log_info("cli [", tag, "] ", command, " -> TIMEOUT no '", cli.ack, "' in ",
                                  timeout_ms, " ms", quoted);
        }
        //only the echo / a lone prompt came back: the board said nothing
        const size_t echo_at = resp.find(command);
        const bool prompt_after_echo = !cli.prompt.empty() && echo_at != string::npos &&
                                       resp.find(cli.prompt, echo_at + command.size()) != string::npos;
        const bool answered = got_ack || !reply.empty() || prompt_after_echo;
        return answered ? resp : std::string();
    } catch (const std::exception& e) {
        io_error_ = true;
        cpsl::radar::log_error("CLIController: '", command, "' failed: ", e.what());
        return std::string();
    } catch (...) {
        io_error_ = true;
        cpsl::radar::log_error("CLIController: '", command, "' failed with an unknown exception");
        return std::string();
    }
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
 * @param tag "i/N" (cfg line), "start" or "stop": printed in the cli echo line
 * @return true if the board responded with "Done"; false on a timeout, a
 *  missing ack, or an I/O error (which also sets io_error()). Never throws.
 */
bool CLIController::sendCommand(const string& command, int timeout_ms, const string& tag) {

    //io_error() describes this command only (core-11 review S2: it used to stick)
    io_error_ = false;

    if (!stream) {
        cpsl::radar::log_error("CLIController: '", command, "' not sent: no CLI port");
        return false;
    }

    const auto t_start = std::chrono::steady_clock::now();

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
        const long long elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t_start).count();

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

        //one echo line per command (info level), written after the reply:
        //  cli [3/27] channelCfg ... -> DONE (12 ms)
        //  cli [27/27] sensorStart -> ERROR (8 ms) "Error: ... | Error -1"
        //  cli [5/27] foo -> TIMEOUT no 'Done' in 100 ms "<partial reply>"
        //An I/O error has no echo line (it is logged as an error below).
        if (!ec || ec == std::errc::timed_out) {
            const string reply = echo_reply(resp, command, cli.ack, cli.prompt);
            const string quoted = reply.empty() ? string() : " \"" + reply + "\"";
            if (!ec) {
                cpsl::radar::log_info("cli [", tag, "] ", command, " -> DONE (", elapsed_ms, " ms)", quoted);
            } else if (reply.find("Error") != string::npos || reply.find("not recognized") != string::npos) {
                cpsl::radar::log_info("cli [", tag, "] ", command, " -> ERROR (", elapsed_ms, " ms)", quoted);
            } else {
                cpsl::radar::log_info("cli [", tag, "] ", command, " -> TIMEOUT no '", cli.ack, "' in ",
                                      timeout_ms, " ms", quoted);
            }
        }

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
