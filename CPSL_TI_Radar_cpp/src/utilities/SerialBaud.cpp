#include "SerialBaud.hpp"

#include <errno.h>
#include <string.h>
#include <termios.h>

#include "Log.hpp"

// Defined in SerialBaudTermios2.cpp, which can't share a translation unit with
// <termios.h> because <asm/termbits.h> redefines it.
bool set_custom_baud_termios2(int fd, unsigned int baud_rate, unsigned int & actual_baud_rate);

namespace {

// the termios constant for a standard rate (the same table boost::asio used), or B0
speed_t standard_speed(unsigned int baud){
    switch(baud){
        case 50: return B50;
        case 75: return B75;
        case 110: return B110;
        case 134: return B134;
        case 150: return B150;
        case 200: return B200;
        case 300: return B300;
        case 600: return B600;
        case 1200: return B1200;
        case 1800: return B1800;
        case 2400: return B2400;
        case 4800: return B4800;
        case 9600: return B9600;
        case 19200: return B19200;
        case 38400: return B38400;
        case 57600: return B57600;
        case 115200: return B115200;
        case 230400: return B230400;
        case 460800: return B460800;
        case 500000: return B500000;
        case 576000: return B576000;
        case 921600: return B921600;
        case 1000000: return B1000000;
        case 1152000: return B1152000;
        case 1500000: return B1500000;
        case 2000000: return B2000000;
        case 2500000: return B2500000;
        case 3000000: return B3000000;
        case 3500000: return B3500000;
        case 4000000: return B4000000;
        default: return B0;
    }
}

}  // namespace

bool set_serial_baud_rate(int fd, unsigned int baud_rate){

    const speed_t speed = standard_speed(baud_rate);
    if(speed != B0){
        termios tio;
        if(::tcgetattr(fd, &tio) == 0 &&
           ::cfsetispeed(&tio, speed) == 0 && ::cfsetospeed(&tio, speed) == 0 &&
           ::tcsetattr(fd, TCSANOW, &tio) == 0){
            return true;
        }
        cpsl::radar::log_debug("set_serial_baud_rate: termios rejected ", baud_rate, " baud (",
                               strerror(errno), "), trying termios2");
    }

    unsigned int actual_baud_rate = 0;
    if(!set_custom_baud_termios2(fd, baud_rate, actual_baud_rate)){
        cpsl::radar::log_error("set_serial_baud_rate: failed to set baud rate ", baud_rate,
                               " (", strerror(errno), ")");
        return false;
    }

    if(actual_baud_rate != baud_rate){
        cpsl::radar::log_error("set_serial_baud_rate: requested ", baud_rate,
                               " baud but the driver applied ", actual_baud_rate,
                               ". The USB-UART bridge may not support this rate.");
        return false;
    }

    return true;
}
