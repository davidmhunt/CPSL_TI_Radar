#include "SystemConfigReader.hpp"

using json = nlohmann::json;

/**
 * @brief Default constructor
 * 
 */
SystemConfigReader::SystemConfigReader()
    : json_file_path(""),
      radar_cliPort(""),
      DCA_fpgaIP(""),
      DCA_systemIP(""),
      DCA_dataPort(0),
      DCA_cmdPort(0),
      save_to_file(false),
      initialized(false)
    {}

/**
 * @brief Constructor that automatically initializes when given a JSON config file path
 * 
 * @param jsonFilePath The path to the system's JSON configuration file
 */
SystemConfigReader::SystemConfigReader(const std::string& jsonFilePath)
    : json_file_path(jsonFilePath),
      radar_cliPort(""),
      DCA_fpgaIP(""),
      DCA_systemIP(""),
      DCA_dataPort(0),
      DCA_cmdPort(0),
      save_to_file(false)
{
    initialize(jsonFilePath);
}

/**
 * @brief Copy constructor (does not initialize though)
 * 
 * @param rhs 
 */
SystemConfigReader::SystemConfigReader(const SystemConfigReader & rhs)
    : json_file_path(rhs.json_file_path),
      radar_cliPort(rhs.radar_cliPort),
      DCA_fpgaIP(rhs.DCA_fpgaIP),
      DCA_systemIP(rhs.DCA_systemIP),
      DCA_dataPort(rhs.DCA_dataPort),
      DCA_cmdPort(rhs.DCA_cmdPort),
      save_to_file(rhs.save_to_file),
      initialized(rhs.initialized)
{}

/**
 * @brief Assignment operator
 * 
 * @param rhs 
 * @return SystemConfigReader& 
 */
SystemConfigReader & SystemConfigReader::operator=(const SystemConfigReader & rhs){
    if(this != &rhs){
        json_file_path = rhs.json_file_path;
        radar_ConfigPath = rhs.radar_ConfigPath;
        radar_cliPort = rhs.radar_cliPort;
        DCA_fpgaIP = rhs.DCA_fpgaIP;
        DCA_systemIP = rhs.DCA_systemIP;
        DCA_dataPort = rhs.DCA_dataPort;
        DCA_cmdPort = rhs.DCA_cmdPort;
        save_to_file = rhs.save_to_file;
        initialized = rhs.initialized;
    }

    return *this;
}

/**
 * @brief initialize the SystemConfigReader with a new json file
 * 
 * @param jsonFilePath path to a JSON config file
 */
void SystemConfigReader::initialize(const std::string & jsonFilePath){
    
    json_file_path = jsonFilePath;
    //read the json file and initialize the SystemConfigReader
    readJsonFile();

    initialized = true;
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

bool SystemConfigReader::get_save_to_file() const 
{
    return save_to_file;
}

void SystemConfigReader::readJsonFile() 
{
    std::ifstream file(json_file_path);
    json data;

    //parse the JSON file
    if (!file.is_open()) {
        std::cerr << "Failed to open JSON file: " << json_file_path << std::endl;
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

    //saving to a file
    if (data.contains("Streamer") && data["Streamer"].contains("save_to_file")) {
        save_to_file = data["Streamer"]["save_to_file"].get<bool>();
    }
}