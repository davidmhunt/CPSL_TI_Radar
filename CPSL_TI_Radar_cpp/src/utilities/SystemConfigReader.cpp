#include "SystemConfigReader.hpp"

using json = nlohmann::json;

/**
 * @brief Construct a new System Config Reader:: System Config Reader object
 * 
 * @param jsonFilePath The path to the system's JSON configuration file
 */
SystemConfigReader::SystemConfigReader(const std::string& jsonFilePath)
    : jsonFilePath(jsonFilePath),
      radar_cliPort(""),
      DCA_fpgaIP(""),
      DCA_systemIP(""),
      DCA_dataPort(0),
      DCA_cmdPort(0)
{
    readJsonFile();
}

std::string SystemConfigReader::getRadarConfigPath() const 
{
    return radar_ConfigPath;
}

std::string SystemConfigReader::getRadarCliPort() const 
{
    return radar_cliPort;
}

std::string SystemConfigReader::getDCAFpgaIP() const 
{
    return DCA_fpgaIP;
}

std::string SystemConfigReader::getDCASystemIP() const 
{
    return DCA_systemIP;
}

int SystemConfigReader::getDCADataPort() const 
{
    return DCA_dataPort;
}

int SystemConfigReader::getDCACmdPort() const 
{
    return DCA_cmdPort;
}

void SystemConfigReader::readJsonFile() 
{
    std::ifstream file(jsonFilePath);
    json data;

    //parse the JSON file
    if (!file.is_open()) {
        std::cerr << "Failed to open JSON file: " << jsonFilePath << std::endl;
        return;
    }
    else{
        data = json::parse(file);
    }

    //get the configuration path
    if (data.contains("TI_Radar_Config_Management") && 
        data["TI_Radar_Config_Management"].contains("TI_Radar_config_path")) {
        radar_ConfigPath = data["TI_Radar_Config_Management"]["TI_Radar_config_path"].get<std::string>();
    }

    //get the radar CLI interface information
    if (data.contains("CLI_Controller") && data["CLI_Controller"].contains("CLI_port")) {
        radar_cliPort = data["CLI_Controller"]["CLI_port"].get<std::string>();
    }

    //get the DCA1000 interface information
    if (data.contains("Streamer") && data["Streamer"].contains("DCA1000_streaming")) {
        json& DCA1000Config = data["Streamer"]["DCA1000_streaming"];
        if (DCA1000Config.contains("FPGA_IP")) {
            DCA_fpgaIP = DCA1000Config["FPGA_IP"].get<std::string>();
        }
        if (DCA1000Config.contains("system_IP")) {
            DCA_systemIP = DCA1000Config["system_IP"].get<std::string>();
        }
        if (DCA1000Config.contains("data_port")) {
            DCA_dataPort = DCA1000Config["data_port"].get<int>();
        }
        if (DCA1000Config.contains("cmd_port")) {
            DCA_cmdPort = DCA1000Config["cmd_port"].get<int>();
        }
    }
}