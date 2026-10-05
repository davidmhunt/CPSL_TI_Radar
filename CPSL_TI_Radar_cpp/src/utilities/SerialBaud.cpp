#include "SerialBaud.hpp"

#include <iostream>

// Defined in SerialBaudTermios2.cpp, which can't share a translation unit with
// <termios.h> (pulled in by boost::asio) because <asm/termbits.h> redefines it.
bool set_custom_baud_termios2(int fd, unsigned int baud_rate, unsigned int & actual_baud_rate);

bool set_serial_baud_rate(boost::asio::serial_port & port, unsigned int baud_rate){

    boost::system::error_code ec;
    port.set_option(boost::asio::serial_port_base::baud_rate(baud_rate), ec);
    if(!ec){
        return true;
    }

    unsigned int actual_baud_rate = 0;
    if(!set_custom_baud_termios2(port.native_handle(), baud_rate, actual_baud_rate)){
        std::cerr << "set_serial_baud_rate: failed to set baud rate " << baud_rate
                  << " (" << ec.message() << ")" << std::endl;
        return false;
    }

    if(actual_baud_rate != baud_rate){
        std::cerr << "set_serial_baud_rate: requested " << baud_rate
                  << " baud but the driver applied " << actual_baud_rate
                  << ". The USB-UART bridge may not support this rate." << std::endl;
        return false;
    }

    return true;
}
