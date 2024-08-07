#ifndef SYSTEM_CONFIG_READER_H
#define SYSTEM_CONFIG_READER_H

#include <string>
#include <iostream>
#include <fstream>
#include "nlohmann/json.hpp"

using json = nlohmann::json;

class SystemConfigReader {
    public:
        SystemConfigReader();
        SystemConfigReader(const std::string& jsonFilePath);
        SystemConfigReader(const SystemConfigReader & rhs);
        SystemConfigReader & operator=(const SystemConfigReader & rhs);

        void initialize(const std::string& jsonFilePath);

        std::string getRadarConfigPath() const;
        std::string getRadarCliPort() const;
        std::string getDCAFpgaIP() const;
        std::string getDCASystemIP() const;
        int getDCADataPort() const;
        int getDCACmdPort() const;
        bool get_save_to_file() const;
        bool get_verbose() const;

        //variable to confirm that the class has been initialized
        bool initialized;
        bool verbose;

    private:
        std::string json_file_path;
        std::string radar_ConfigPath;
        std::string radar_cliPort;
        std::string DCA_fpgaIP;
        std::string DCA_systemIP;
        int DCA_dataPort;
        int DCA_cmdPort;
        bool save_to_file;

        void readJsonFile();
};

#endif // RADAR_CONFIG_READER_H