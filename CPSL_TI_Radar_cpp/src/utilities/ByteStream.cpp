#include "ByteStream.hpp"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

#include <algorithm>

#include "SerialBaud.hpp"

namespace cpsl {
namespace radar {

namespace {

using clk = std::chrono::steady_clock;

std::error_code last_error() { return std::error_code(errno, std::system_category()); }

// milliseconds left until `deadline` (0 if it has passed), rounded up
int ms_left(clk::time_point deadline) {
    const auto left = deadline - clk::now();
    if (left <= clk::duration::zero()) return 0;
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(left + std::chrono::microseconds(999));
    return static_cast<int>(std::min<int64_t>(ms.count(), 1 << 30));
}

// Wait for `events` on fd until `deadline`. 0 = ready; timed_out; or the error.
std::error_code wait_for(int fd, short events, clk::time_point deadline) {
    for (;;) {
        pollfd p{fd, events, 0};
        const int r = ::poll(&p, 1, ms_left(deadline));
        if (r < 0) {
            if (errno == EINTR) continue;
            return last_error();
        }
        if (r == 0) return std::make_error_code(std::errc::timed_out);
        if (p.revents & events) return std::error_code();
        // POLLERR / POLLHUP / POLLNVAL without the event: the device is gone
        return std::make_error_code(std::errc::io_error);
    }
}

}  // namespace

SerialPortStream::~SerialPortStream() {
    if (fd_ >= 0) ::close(fd_);  // never throws, even if the device is gone
}

std::shared_ptr<SerialPortStream> SerialPortStream::open(const std::string& port, unsigned int baud,
                                                         std::string& error) {
    const int fd = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        error = "cannot open " + port + ": " + last_error().message();
        return nullptr;
    }
    std::shared_ptr<SerialPortStream> s(new SerialPortStream(fd));

    // raw mode, as the asio serial_port::open set it before core-16:
    // cfmakeraw, ignore parity errors, receiver on, modem lines ignored
    termios tio{};
    if (::tcgetattr(fd, &tio) != 0) {
        error = "cannot read the termios settings of " + port + ": " + last_error().message();
        return nullptr;
    }
    ::cfmakeraw(&tio);
    tio.c_iflag |= IGNPAR;
    tio.c_cflag |= CREAD | CLOCAL;
    if (::tcsetattr(fd, TCSANOW, &tio) != 0) {
        error = "cannot set raw mode on " + port + ": " + last_error().message();
        return nullptr;
    }
    if (!set_serial_baud_rate(fd, baud)) {
        error = "cannot set " + port + " to " + std::to_string(baud) + " baud";
        return nullptr;
    }
    return s;
}

std::error_code SerialPortStream::write(const uint8_t* data, size_t len, std::chrono::milliseconds timeout) {
    const clk::time_point deadline = clk::now() + timeout;
    size_t done = 0;
    while (done < len) {
        const ssize_t w = ::write(fd_, data + done, len - done);
        if (w > 0) {
            done += static_cast<size_t>(w);
            continue;
        }
        if (w < 0 && errno == EINTR) continue;
        if (w < 0 && errno != EAGAIN && errno != EWOULDBLOCK) return last_error();
        // the output buffer is full: wait for room, but not past the deadline
        const std::error_code ec = wait_for(fd_, POLLOUT, deadline);
        if (ec) return ec;
    }
    return std::error_code();
}

void SerialPortStream::discard_input() {
    if (fd_ >= 0) (void)tcflush(fd_, TCIFLUSH);
}

std::error_code SerialPortStream::read_some(uint8_t* buf, size_t cap, size_t& n,
                                            std::chrono::milliseconds timeout) {
    n = 0;
    if (cap == 0) return std::error_code();
    const clk::time_point deadline = clk::now() + timeout;
    for (;;) {
        const ssize_t r = ::read(fd_, buf, cap);
        if (r > 0) {
            n = static_cast<size_t>(r);
            return std::error_code();
        }
        if (r == 0) return std::make_error_code(std::errc::io_error);  // hang-up: the device is gone
        if (errno == EINTR) continue;
        if (errno != EAGAIN && errno != EWOULDBLOCK) return last_error();
        const std::error_code ec = wait_for(fd_, POLLIN, deadline);
        if (ec) return ec;
    }
}

}  // namespace radar
}  // namespace cpsl
