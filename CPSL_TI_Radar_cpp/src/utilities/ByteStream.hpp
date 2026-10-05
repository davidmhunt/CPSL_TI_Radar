#ifndef CPSL_RADAR_BYTE_STREAM_HPP
#define CPSL_RADAR_BYTE_STREAM_HPP

// ByteStream: the minimal byte-level seam under the CLI controller (design §3
// "Internal seams for tests"; directive core-11, reused by core-13). Read and
// write only. SerialPortStream is the real serial port; tests substitute a
// fake to script replies and inject I/O errors (e.g. a USB unplug).
//
// Neither call is meant to throw: errors come back as a std::error_code.
// Callers still guard against a throwing implementation.

#include <boost/asio.hpp>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <system_error>

namespace cpsl {
namespace radar {

class ByteStream {
public:
    virtual ~ByteStream() = default;

    // Write all `len` bytes. A non-zero error means the write failed.
    virtual std::error_code write(const uint8_t* data, size_t len) = 0;

    // Wait at most `timeout` for data and read up to `cap` bytes into `buf`;
    // `n` is the count read. No data in time: std::errc::timed_out, n == 0.
    virtual std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) = 0;
};

// A serial port (boost::asio) at a given baud rate.
class SerialPortStream : public ByteStream {
public:
    // Opens `port` and sets `baud`. Returns nullptr and fills `error` on failure.
    static std::shared_ptr<SerialPortStream> open(const std::string& port, unsigned int baud, std::string& error);
    ~SerialPortStream() override;

    std::error_code write(const uint8_t* data, size_t len) override;
    std::error_code read_some(uint8_t* buf, size_t cap, size_t& n, std::chrono::milliseconds timeout) override;

private:
    SerialPortStream();
    boost::asio::io_context io_;
    boost::asio::serial_port port_;
};

}  // namespace radar
}  // namespace cpsl

#endif
