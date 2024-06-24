#include "RadarConfigReader.hpp"
#include <iostream>

RadarConfigReader::RadarConfigReader(const std::string& filename) {
    cfg_file.open(filename);
    if (!cfg_file.is_open()) {
        std::cerr << "Error opening file: " << filename << std::endl;
    }else{
        //process the configuration
        process_cfg();

        //set the number of rx antennas
        rx_antennas = 4;
    }
}

RadarConfigReader::~RadarConfigReader()
{
    if (cfg_file.is_open()) {
        cfg_file.close();
    }
}

size_t RadarConfigReader::get_bytes_per_frame(){
    
    //number of bytes per sample (assuming complex samples)
    size_t bytes_per_sample = 4;

    //number of chirps per frame
    size_t chirps_per_frame = static_cast<size_t>(get_chirps_per_frame());

    return bytes_per_sample * 
        static_cast<size_t>(rx_antennas) * 
        static_cast<size_t>(profileCfg_adc_samples) * 
        chirps_per_frame;

}

size_t RadarConfigReader::get_chirps_per_frame(){
    return static_cast<size_t>(frameCfg_chirp_end_idx - frameCfg_chirp_start_idx + 1) * frameCfG_num_loops;
}

size_t RadarConfigReader::get_samples_per_chirp(){
    return static_cast<size_t>(profileCfg_adc_samples);
}

void RadarConfigReader::process_cfg() {
    std::string line;
    while (std::getline(cfg_file, line)) {
        std::istringstream iss(line);
        std::string key;
        if (std::getline(iss, key, ' ')) {
            if (key == "profileCfg") {
                read_profile_cfg(get_vec_from_string(line));
            }
            if (key == "chirpCfg") {
                read_chirp_cfg(get_vec_from_string(line));
            }
            if (key == "frameCfg") {
                read_frame_cfg(get_vec_from_string(line));
            }
        }
    }
}

std::vector<std::string> RadarConfigReader::get_vec_from_string(std::string text)
{
    std::istringstream iss(text);
    std::string value;
    std::vector<std::string> values;
    while (std::getline(iss,value,' '))
    {
        values.push_back(value);
    }  

    return values;
}

void RadarConfigReader::read_profile_cfg(std::vector<std::string> values){
    
    //set the profile config
    profileCfg_chirp_start_freq_GHz = std::stof(values[2]);
    profileCfg_idle_time_us = std::stof(values[3]);
    profileCfg_ramp_end_time_us = std::stof(values[5]);
    profileCfg_adc_samples = (std::stoi(values[10]));
    profileCfg_adc_sample_rate_ksps = (std::stoi(values[11]));
}

void RadarConfigReader::read_chirp_cfg(std::vector<std::string> values){
    
    //set the chirp config
    chirpCfg_start_idx = (std::stoi(values[1]));
    chirpCfg_end_idx = (std::stoi(values[2]));
}

void RadarConfigReader::read_frame_cfg(std::vector<std::string> values){
    
    //set the profile config
    frameCfg_chirp_start_idx = (std::stoi(values[1]));
    frameCfg_chirp_end_idx = (std::stoi(values[2]));
    frameCfG_num_loops = (std::stoi(values[3]));
    frameCfg_frame_period = std::stof(values[5]);   
}