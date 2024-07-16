#include "RadarConfigReaderDONE.hpp"
#include <iostream>
#include <fstream>
#include "json.hpp"

using json = nlohmann::json;

RadarConfigReader::RadarConfigReader(const std::string& jsonFilePath)
    : m_jsonFilePath(jsonFilePath),
      m_cliPort(""),
      m_fpgaIP(""),
      m_systemIP(""),
      m_dataPort(0),
      m_cmdPort(0) {
    readJsonFile();
}

std::string RadarConfigReader::getRadarConfigPath() const {
    return m_radarConfigPath;
}

std::string RadarConfigReader::getCliPort() const {
    return m_cliPort;
}

std::string RadarConfigReader::getFpgaIP() const {
    return m_fpgaIP;
}

std::string RadarConfigReader::getSystemIP() const {
    return m_systemIP;
}

int RadarConfigReader::getDataPort() const {
    return m_dataPort;
}

int RadarConfigReader::getCmdPort() const {
    return m_cmdPort;
}

void RadarConfigReader::readJsonFile() {
    std::ifstream file(m_jsonFilePath);
    if (!file.is_open()) {
        std::cerr << "Failed to open JSON file: " << m_jsonFilePath << std::endl;
        return;
    }

    json data;
    file >> data;

    if (data.contains("TI_Radar_Config_Management") && data["TI_Radar_Config_Management"].contains("TI_Radar_config_path")) {
        m_radarConfigPath = data["TI_Radar_Config_Management"]["TI_Radar_config_path"].get<std::string>();
    }

    if (data.contains("CLI_Controller") && data["CLI_Controller"].contains("CLI_port")) {
        m_cliPort = data["CLI_Controller"]["CLI_port"].get<std::string>();
    }

    if (data.contains("Streamer") && data["Streamer"].contains("DCA1000_streaming")) {
        json& dca1000Streaming = data["Streamer"]["DCA1000_streaming"];
        if (dca1000Streaming.contains("FPGA_IP")) {
            m_fpgaIP = dca1000Streaming["FPGA_IP"].get<std::string>();
        }
        if (dca1000Streaming.contains("system_IP")) {
            m_systemIP = dca1000Streaming["system_IP"].get<std::string>();
        }
        if (dca1000Streaming.contains("data_port")) {
            m_dataPort = dca1000Streaming["data_port"].get<int>();
        }
        if (dca1000Streaming.contains("cmd_port")) {
            m_cmdPort = dca1000Streaming["cmd_port"].get<int>();
        }
    }
}