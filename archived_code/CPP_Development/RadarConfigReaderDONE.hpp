#ifndef RADAR_CONFIG_READER_H
#define RADAR_CONFIG_READER_DONE_H

#include <string>

class RadarConfigReader {
public:
    RadarConfigReader(const std::string& jsonFilePath);

    std::string getRadarConfigPath() const;
    std::string getCliPort() const;
    std::string getFpgaIP() const;
    std::string getSystemIP() const;
    int getDataPort() const;
    int getCmdPort() const;

private:
    std::string m_jsonFilePath;
    std::string m_radarConfigPath;
    std::string m_cliPort;
    std::string m_fpgaIP;
    std::string m_systemIP;
    int m_dataPort;
    int m_cmdPort;

    void readJsonFile();
};

#endif // RADAR_CONFIG_READER_H