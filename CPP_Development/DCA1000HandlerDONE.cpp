#include "DCA1000HandlerDONE.hpp"
#include "RadarConfigReaderDONE.hpp"
#include <iostream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>

DCA1000::DCA1000(const RadarConfigReader& configReader)
    : m_fpgaIP(configReader.getFpgaIP()),
      m_systemIP(configReader.getSystemIP()),
      m_configPort(configReader.getCmdPort()),
      m_dataPort(configReader.getDataPort()),
      m_configSocket(-1) {}

DCA1000::~DCA1000() {
    if (m_configSocket >= 0) {
        close(m_configSocket);
    }
}

bool DCA1000::binding() {
    if (m_configSocket >= 0) {
        close(m_configSocket);
    }
    // Create socket
    m_configSocket = socket(AF_INET, SOCK_DGRAM, 0);
    if (m_configSocket < 0) {
        std::cerr << "Failed to create socket" << std::endl;
        return false;
    }

    // Set socket timeout
    struct timeval timeout;
    timeout.tv_sec = 1;
    timeout.tv_usec = 0;
    setsockopt(m_configSocket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    //set up addresses
   // struct sockaddr_in configAddr;
    //configAddr.sin_family = AF_INET;
   // configAddr.sin_addr.s_addr = inet_addr(m_systemIP.c_str());
   // configAddr.sin_port = htons(m_dataPort);

    std::cout << m_systemIP << "\n";
    std::cout << m_dataPort;

    // Bind socket to receive at the system IP and config port
    struct sockaddr_in configAddr;
    configAddr.sin_family = AF_INET;
    configAddr.sin_port = htons(m_dataPort);
    inet_pton(AF_INET, m_systemIP.c_str(), &(configAddr.sin_addr));

    if (bind(m_configSocket, (struct sockaddr*)&configAddr, sizeof(configAddr)) < 0) {
        std::cerr << "Failed to bind socket" << std::endl;
        close(m_configSocket);
        m_configSocket = -1;
        return false;
    }

    return true;
}

bool DCA1000::sendCommand(const uint8_t* command, size_t commandSize) {
    if (m_configSocket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    struct sockaddr_in fpgaAddr;
    fpgaAddr.sin_family = AF_INET;
    fpgaAddr.sin_port = htons(m_configPort);
    inet_pton(AF_INET, m_fpgaIP.c_str(), &(fpgaAddr.sin_addr));

    ssize_t sentBytes = sendto(m_configSocket, command, commandSize, 0,
                               (struct sockaddr*)&fpgaAddr, sizeof(fpgaAddr));
    if (sentBytes != static_cast<ssize_t>(commandSize)) {
        std::cerr << "Failed to send command" << std::endl;
        return false;
    }

    return true;
}

bool DCA1000::receiveResponse(uint8_t* buffer, size_t bufferSize, ssize_t& receivedBytes) {
    if (m_configSocket < 0) {
        std::cerr << "Socket not bound" << std::endl;
        return false;
    }

    struct sockaddr_in fromAddr;
    socklen_t fromLen = sizeof(fromAddr);
    receivedBytes = recvfrom(m_configSocket, buffer, bufferSize, 0,
                             (struct sockaddr*)&fromAddr, &fromLen);
    if (receivedBytes < 0) {
        std::cerr << "Failed to receive data" << std::endl;
        return false;
    }

    return true;
}