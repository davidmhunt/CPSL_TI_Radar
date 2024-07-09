#ifndef SYSTEM_CONFIG_READER_H
#define SYSTEM_CONFIG_READER_H

#include <string>
#include <iostream>
#include <fstream>
#include "nlohmann/json.hpp"

using json = nlohmann::json;

class SystemConfigReader {
    public:
        SystemConfigReader(const std::string& jsonFilePath);

        std::string getRadarConfigPath() const;
        std::string getRadarCliPort() const;
        std::string getDCAFpgaIP() const;
        std::string getDCASystemIP() const;
        int getDCADataPort() const;
        int getDCACmdPort() const;
        bool get_save_to_file() const;

    private:
        std::string jsonFilePath;
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