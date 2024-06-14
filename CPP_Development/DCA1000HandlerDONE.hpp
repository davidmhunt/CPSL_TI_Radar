#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>

class RadarConfigReader;

class DCA1000 {
public:
    DCA1000(const RadarConfigReader& configReader);
    ~DCA1000();

    bool bind();
    bool sendCommand(const uint8_t* command, size_t commandSize);
    bool receiveResponse(uint8_t* buffer, size_t bufferSize, ssize_t& receivedBytes);

private:
    std::string m_fpgaIP;
    std::string m_systemIP;
    int m_configPort;
    int m_dataPort;
    int m_configSocket;
};

#endif // DCA1000_H