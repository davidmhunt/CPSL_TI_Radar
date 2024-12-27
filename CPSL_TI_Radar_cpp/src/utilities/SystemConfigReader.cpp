#include "SystemConfigReader.hpp"

using json = nlohmann::json;

/**
 * @brief Default constructor
 * 
 */
SystemConfigReader::SystemConfigReader()
    : initialized(false),
      verbose(false),
      json_file_path(""),
      radar_cliPort(""),
      DCA_fpgaIP(""),
      DCA_systemIP(""),
      DCA_dataPort(0),
      DCA_cmdPort(0),
      save_to_file(false),
      sdk_version(""),
      sdk_major_version(0),
      sdk_minor_version(0)
    {}

/**
 * @brief Constructor that automatically initializes when given a JSON config file path
 * 
 * @param jsonFilePath The path to the system's JSON configuration file
 */
SystemConfigReader::SystemConfigReader(const std::string& jsonFilePath)
    : initialized(false),
      verbose(false), json_file_path(jsonFilePath),
      radar_cliPort(""),
      DCA_fpgaIP(""),
      DCA_systemIP(""),
      DCA_dataPort(0),
      DCA_cmdPort(0),
      save_to_file(false),
      sdk_version(""),
      sdk_major_version(0),
      sdk_minor_version(0)
{
    initialize(jsonFilePath);
}

/**
 * @brief Copy constructor (does not initialize though)
 * 
 * @param rhs 
 */
SystemConfigReader::SystemConfigReader(const SystemConfigReader & rhs)
    : initialized(rhs.initialized),
      verbose(rhs.verbose),
      json_file_path(rhs.json_file_path),
      radar_cliPort(rhs.radar_cliPort),
      DCA_fpgaIP(rhs.DCA_fpgaIP),
      DCA_systemIP(rhs.DCA_systemIP),
      DCA_dataPort(rhs.DCA_dataPort),
      DCA_cmdPort(rhs.DCA_cmdPort),
      save_to_file(rhs.save_to_file),
      sdk_version(rhs.sdk_version),
      sdk_major_version(rhs.sdk_major_version),
      sdk_minor_version(rhs.sdk_minor_version)
{}

/**
 * @brief Assignment operator
 * 
 * @param rhs 
 * @return SystemConfigReader& 
 */
SystemConfigReader & SystemConfigReader::operator=(const SystemConfigReader & rhs){
    if(this != &rhs){
        initialized = rhs.initialized;
        verbose = rhs.verbose;
        json_file_path = rhs.json_file_path;
        radar_ConfigPath = rhs.radar_ConfigPath;
        radar_cliPort = rhs.radar_cliPort;
        DCA_fpgaIP = rhs.DCA_fpgaIP;
        DCA_systemIP = rhs.DCA_systemIP;
        DCA_dataPort = rhs.DCA_dataPort;
        DCA_cmdPort = rhs.DCA_cmdPort;
        save_to_file = rhs.save_to_file;
        sdk_version = rhs.sdk_version;
        sdk_major_version = rhs.sdk_major_version;
        sdk_minor_version = rhs.sdk_minor_version;
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

bool SystemConfigReader::get_verbose() const
{
    return verbose;
}

int SystemConfigReader::getSDKMajorVersion() const
{
    return sdk_major_version;
}

int SystemConfigReader::getSDKMinorVersion() const
{
    return sdk_minor_version;
}

void SystemConfigReader::readJsonFile() 
{
    std::ifstream file(json_file_path);
    json data;

    //parse the JSON file
    if (!file.is_open()) {
        std::cerr << "SystemConfigReader: failed to open JSON file: " << json_file_path << std::endl;
        return;
    }
    else{
        data = json::parse(file);
    }

    //get the verbose status
    if (data.contains("verbose")){
        verbose = data["verbose"].get<bool>();
    } else{
        initialized = false;
        std::cerr << "SystemConfigReader: Couldn't find verbose" << std::endl;
        return;
    }

    //get the configuration path
    if (data.contains("TI_Radar_Config_Management") && 
        data["TI_Radar_Config_Management"].contains("TI_Radar_config_path")) {
        radar_ConfigPath = data["TI_Radar_Config_Management"]["TI_Radar_config_path"].get<std::string>();
    } else{
        initialized = false;
        std::cerr << "SystemConfigReader: Couldn't find TI_Radar_config_path" << std::endl;
        return;
    }

    //get the radar CLI interface information
    if (data.contains("CLI_Controller") && data["CLI_Controller"].contains("CLI_port")) {
        radar_cliPort = data["CLI_Controller"]["CLI_port"].get<std::string>();
    } else{
        initialized = false;
        std::cerr << "SystemConfigReader: Couldn't find CLI_port"<< std::endl;
        return;
    }

    //get the DCA1000 interface information
    if (data.contains("Streamer")) {
        //dca1000 streaming
        if (data["Streamer"].contains("DCA1000_streaming")){
            json& DCA1000Config = data["Streamer"]["DCA1000_streaming"];
            if (DCA1000Config.contains("FPGA_IP")) {
                DCA_fpgaIP = DCA1000Config["FPGA_IP"].get<std::string>();
            } else{
                initialized = false;
                std::cerr << "SystemConfigReader: Couldn't find FPGA_IP"<< std::endl;
                return;
            }
            if (DCA1000Config.contains("system_IP")) {
                DCA_systemIP = DCA1000Config["system_IP"].get<std::string>();
            } else{
                initialized = false;
                std::cerr << "SystemConfigReader: Couldn't find system_IP"<< std::endl;
                return;
            }
            if (DCA1000Config.contains("data_port")) {
                DCA_dataPort = DCA1000Config["data_port"].get<int>();
            } else{
                initialized = false;
                std::cerr << "SystemConfigReader: Couldn't find data_port"<< std::endl;
                return;
            }
            if (DCA1000Config.contains("cmd_port")) {
                DCA_cmdPort = DCA1000Config["cmd_port"].get<int>();
            } else{
                initialized = false;
                std::cerr << "SystemConfigReader: Couldn't find cmd_port"<< std::endl;
                return;
            }
        }

        //saving to a file
        if (data["Streamer"].contains("save_to_file")) {
            save_to_file = data["Streamer"]["save_to_file"].get<bool>();
        }else{
            initialized = false;
            std::cerr << "SystemConfigReader: Couldn't find save_to_file"<< std::endl;
            return;
        }

        //SDK versioning
        if (data["Streamer"].contains("SDK_version")) {
            sdk_version = data["Streamer"]["SDK_version"].get<std::string>();

            std::stringstream ss(sdk_version);
            char dot;
            ss >> sdk_major_version >> dot >> sdk_minor_version;
        }else{
            initialized = false;
            std::cerr << "SystemConfigReader: Couldn't find SDK_version"<< std::endl;
            return;
        }
    }else{
        initialized = false;
        std::cerr << "SystemConfigReader: Couldn't find Streamer"<< std::endl;
        return;
    }  

    initialized = true;
}