#include "ByteStream.hpp"

#include "SerialBaud.hpp"

namespace cpsl {
namespace radar {

namespace {
std::error_code to_std(const boost::system::error_code& ec) {
    return ec ? std::error_code(ec.value(), std::system_category()) : std::error_code();
}
}  // namespace

SerialPortStream::SerialPortStream() : io_(), port_(io_) {}

SerialPortStream::~SerialPortStream() {
    boost::system::error_code ec;
    port_.close(ec);  // never throws, even if the device is gone
}

std::shared_ptr<SerialPortStream> SerialPortStream::open(const std::string& port, unsigned int baud,
                                                         std::string& error) {
    std::shared_ptr<SerialPortStream> s(new SerialPortStream());
    boost::system::error_code ec;
    s->port_.open(port, ec);
    if (ec) {
        error = "cannot open " + port + ": " + ec.message();
        return nullptr;
    }
    try {
        if (!set_serial_baud_rate(s->port_, baud)) {
            error = "cannot set " + port + " to " + std::to_string(baud) + " baud";
            return nullptr;
        }
    } catch (const std::exception& e) {
        error = "cannot set " + port + " to " + std::to_string(baud) + " baud: " + e.what();
        return nullptr;
    }
    return s;
}

std::error_code SerialPortStream::write(const uint8_t* data, size_t len, std::chrono::milliseconds timeout) {
    boost::system::error_code write_ec;
    bool done = false;
    bool timed_out = false;
    boost::asio::steady_timer timer(io_);
    timer.expires_after(timeout);

    boost::asio::async_write(port_, boost::asio::buffer(data, len),
                             [&](const boost::system::error_code& e, size_t) {
                                 write_ec = e;
                                 done = true;
                                 boost::system::error_code ignore;
                                 timer.cancel(ignore);
                             });
    timer.async_wait([&](const boost::system::error_code& e) {
        if (!e) {
            timed_out = true;
            boost::system::error_code ignore;
            port_.cancel(ignore);  // completes the write with operation_aborted
        }
    });

    io_.restart();
    io_.run();

    if (done && !write_ec) return std::error_code();
    if (timed_out) return std::make_error_code(std::errc::timed_out);
    return to_std(write_ec);
}

std::error_code SerialPortStream::read_some(uint8_t* buf, size_t cap, size_t& n,
                                            std::chrono::milliseconds timeout) {
    n = 0;
    boost::system::error_code read_ec;
    bool timed_out = false;
    boost::asio::steady_timer timer(io_);
    timer.expires_after(timeout);

    port_.async_read_some(boost::asio::buffer(buf, cap),
                          [&](const boost::system::error_code& e, size_t got) {
                              read_ec = e;
                              n = got;
                              boost::system::error_code ignore;
                              timer.cancel(ignore);
                          });
    timer.async_wait([&](const boost::system::error_code& e) {
        if (!e) {
            timed_out = true;
            boost::system::error_code ignore;
            port_.cancel(ignore);
        }
    });

    io_.restart();
    io_.run();

    if (n > 0) return std::error_code();
    if (timed_out) return std::make_error_code(std::errc::timed_out);
    if (read_ec) return to_std(read_ec);
    return std::make_error_code(std::errc::timed_out);
}

}  // namespace radar
}  // namespace cpsl
