#include <asm/termbits.h>
#include <sys/ioctl.h>

/**
 * @brief Set an arbitrary baud rate with termios2/BOTHER, then read the rate
 * back since drivers may round it to the nearest supported value.
 */
bool set_custom_baud_termios2(int fd, unsigned int baud_rate, unsigned int & actual_baud_rate){

    struct termios2 tio;
    if(ioctl(fd, TCGETS2, &tio) != 0){
        return false;
    }

    tio.c_cflag &= ~(CBAUD | (CBAUD << IBSHIFT));
    tio.c_cflag |= BOTHER | (BOTHER << IBSHIFT);
    tio.c_ispeed = baud_rate;
    tio.c_ospeed = baud_rate;
    if(ioctl(fd, TCSETS2, &tio) != 0){
        return false;
    }

    if(ioctl(fd, TCGETS2, &tio) != 0){
        return false;
    }
    actual_baud_rate = tio.c_ospeed;
    return true;
}
