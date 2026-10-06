#ifndef CLICONTROLLER
#define CLICONTROLLER

#include <string>
#include <iostream>
#include <fstream>
#include <memory>
#include <system_error>
#include "SystemConfigReader.hpp"
#include "ByteStream.hpp"

/**
 * @brief Sends the radar cfg and the start/stop commands over the CLI port.
 *
 * The port is a cpsl::radar::ByteStream: the serial port in the driver, a
 * fake in tests. No call throws: a failed write or read (e.g. the radar's USB
 * was unplugged) makes that command return false and sets io_error().
 */
class CLIController {
public:
    CLIController();
    CLIController(const SystemConfigReader & systemConfigReader);
    CLIController(const CLIController & rhs) = default;
    CLIController & operator=(const CLIController & rhs) = default;
    ~CLIController() = default;

    //opens the CLI serial port named by the system config
    bool initialize(const SystemConfigReader & systemConfigReader);
    //uses an already open stream (tests: a fake ByteStream)
    bool initialize(const SystemConfigReader & systemConfigReader,
                    std::shared_ptr<cpsl::radar::ByteStream> stream);

    bool send_config_to_IWR();
    bool sendStartCommand();
    bool sendStopCommand();

    //true if the last command hit a write or read error (not a mere missing
    //"Done"); cleared at the start of every command. A prompt-read error
    //after a "Done" sets it but does not fail that command. After
    //send_config_to_IWR(): true only if a command that failed hit an I/O
    //error (an acknowledged command's prompt-read error is a warning).
    bool io_error() const { return io_error_; }

    //frame period of the radar cfg, for the computed stop timeout
    void set_frame_period_ms(float ms) { frame_period_ms_ = ms; }
    //how long sendStopCommand() waits for the ack: cli.stop_timeout_ms if
    //the board sets it, else max(cli.cmd_timeout_ms, frame period + 200 ms)
    //(the demo acks sensorStop only after the current frame ends)
    int stop_timeout_ms() const;

    bool initialized;
    
private:

    //timeout_ms: how long to wait for the ack (and the most the write may take)
    bool sendCommand(const std::string& command, int timeout_ms);
    //append to `response` until it contains `delim`, or timeout_ms passes
    std::error_code read_until_with_timeout(
        std::string & response,
        const std::string & delim,
        int timeout_ms);

    std::shared_ptr<cpsl::radar::ByteStream> stream;
    SystemConfigReader system_config_reader;
    bool io_error_;
    float frame_period_ms_ = 0.0f;
};

#endif
