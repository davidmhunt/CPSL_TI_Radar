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

    //true once a write or read on the port has failed (not a mere missing "Done")
    bool io_error() const { return io_error_; }

    bool initialized;
    
private:

    bool sendCommand(const std::string& command);
    //append to `response` until it contains `delim`, or timeout_ms passes
    std::error_code read_until_with_timeout(
        std::string & response,
        const std::string & delim,
        int timeout_ms);

    std::shared_ptr<cpsl::radar::ByteStream> stream;
    SystemConfigReader system_config_reader;
    bool io_error_;
};

#endif
