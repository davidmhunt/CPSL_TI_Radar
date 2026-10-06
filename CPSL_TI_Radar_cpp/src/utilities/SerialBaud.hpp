#ifndef SERIAL_BAUD_H
#define SERIAL_BAUD_H

/**
 * @brief Set the baud rate of an open serial port. Standard rates (those
 * with a termios Bxxx constant, up to B4000000) go through
 * cfsetispeed/cfsetospeed; other rates (e.g. the AWR2243 cascade demo's
 * 3125000) are set with termios2/BOTHER on Linux and read back, since a
 * driver may round them.
 *
 * @param fd an open serial port
 * @param baud_rate the desired baud rate
 * @return true if the rate was applied
 */
bool set_serial_baud_rate(int fd, unsigned int baud_rate);

#endif
