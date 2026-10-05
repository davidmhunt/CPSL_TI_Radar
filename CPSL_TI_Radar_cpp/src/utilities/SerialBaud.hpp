#ifndef SERIAL_BAUD_H
#define SERIAL_BAUD_H

#include <boost/asio.hpp>

/**
 * @brief Set the baud rate of an open serial port. Standard rates go through
 * boost::asio; rates boost rejects (e.g. the AWR2243 cascade demo's 3125000)
 * are set with termios2/BOTHER on Linux.
 *
 * @param port an open serial port
 * @param baud_rate the desired baud rate
 * @return true if the rate was applied
 */
bool set_serial_baud_rate(boost::asio::serial_port & port, unsigned int baud_rate);

#endif
