#include "RadarConfigReader.hpp"

/**
 * @brief default constructor
*/
RadarConfigReader::RadarConfigReader():
    initialized(false),
    cfg_file(nullptr)
{}

/**
 * @brief Constructor with initialization
 * 
 * @param filename 
 */
RadarConfigReader::RadarConfigReader(const std::string& filename):
    initialized(false),
    cfg_file(nullptr)
{
    initialize(filename);
}

RadarConfigReader::RadarConfigReader(const RadarConfigReader & rhs):
    initialized(rhs.initialized),
    cfg_file(rhs.cfg_file),
    rx_antennas(rhs.rx_antennas),
    profileCfg_chirp_start_freq_GHz(rhs.profileCfg_chirp_start_freq_GHz),
    profileCfg_idle_time_us(rhs.profileCfg_idle_time_us),
    profileCfg_ramp_end_time_us(rhs.profileCfg_ramp_end_time_us),
    profileCfg_adc_samples(rhs.profileCfg_adc_samples),
    profileCfg_adc_sample_rate_ksps(rhs.profileCfg_adc_sample_rate_ksps),
    chirpCfg_start_idx(rhs.chirpCfg_start_idx),
    chirpCfg_end_idx(rhs.chirpCfg_end_idx),
    frameCfg_chirp_start_idx(rhs.frameCfg_chirp_start_idx),
    frameCfg_chirp_end_idx(rhs.frameCfg_chirp_end_idx),
    frameCfG_num_loops(rhs.frameCfG_num_loops),
    frameCfg_frame_period(rhs.frameCfg_frame_period)
{}

RadarConfigReader & RadarConfigReader::operator=(const RadarConfigReader & rhs){
    if(this != & rhs){

        //close the config file stream if it is open right now
        if(cfg_file.get() != nullptr &&
            cfg_file.use_count() == 1 &&
            cfg_file -> is_open()){
                cfg_file -> close();
            }
        
        //assign all variables to the rhs radar config reader
        initialized = rhs.initialized;
        cfg_file = rhs.cfg_file;
        rx_antennas = rhs.rx_antennas;
        profileCfg_chirp_start_freq_GHz = rhs.profileCfg_chirp_start_freq_GHz;
        profileCfg_idle_time_us = rhs.profileCfg_idle_time_us;
        profileCfg_ramp_end_time_us = rhs.profileCfg_ramp_end_time_us;
        profileCfg_adc_samples = rhs.profileCfg_adc_samples;
        profileCfg_adc_sample_rate_ksps = rhs.profileCfg_adc_sample_rate_ksps;
        chirpCfg_start_idx = rhs.chirpCfg_start_idx;
        chirpCfg_end_idx = rhs.chirpCfg_end_idx;
        frameCfg_chirp_start_idx = rhs.frameCfg_chirp_start_idx;
        frameCfg_chirp_end_idx = rhs.frameCfg_chirp_end_idx;
        frameCfG_num_loops = rhs.frameCfG_num_loops;
        frameCfg_frame_period = rhs.frameCfg_frame_period;
    }

    return *this;
}

RadarConfigReader::~RadarConfigReader()
{   
    if (cfg_file.get() != nullptr &&
        cfg_file.use_count() == 1 &&
        cfg_file -> is_open()){
            cfg_file -> close();
        }
}

void RadarConfigReader::initialize(const std::string & filename){

    //check to make sure that the file stream hasn't already been initialized
    if(cfg_file.get() != nullptr &&
        cfg_file.use_count() == 1 &&
        cfg_file -> is_open())
    {
        cfg_file -> close();
    }

    cfg_file = std::make_shared<std::ifstream>();
    cfg_file -> open(filename);
    if (! cfg_file -> is_open()){
        std::cerr << "Error opening file: " << filename << std::endl;
        initialized = false;
    } else{

        //process the configuration
        process_cfg();

        //set the number of rx antennas
        //TODO: remove the hardcoding when possible
        rx_antennas = 4;

        initialized = true;
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

size_t RadarConfigReader::get_num_rx_antennas(){
    return static_cast<size_t>(rx_antennas);
}

void RadarConfigReader::process_cfg() {

    if(cfg_file.get() != nullptr &&
        cfg_file -> is_open())
    {
        std::string line;
        while (std::getline(*cfg_file, line)) {
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
    }else{
        std::cerr << "attempted to process radar config, but cfg_file isn't open" << std::endl;
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