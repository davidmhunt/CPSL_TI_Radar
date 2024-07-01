#ifndef RADAR_CONFIG_READER_H
#define RADAR_CONFIG_READER_H

#include <fstream>
#include <string>
#include <iostream>
#include <sstream>
#include <vector>

class RadarConfigReader{
    public:
        RadarConfigReader(const std::string& filename);
        ~RadarConfigReader();

        //functions to get specific variables
        size_t get_bytes_per_frame();
        size_t get_chirps_per_frame();
        size_t get_samples_per_chirp();
        size_t get_num_rx_antennas();

    private:
        std::ifstream cfg_file;

        //functions to read the cfg file
        void process_cfg();
        std::vector<std::string> get_vec_from_string(std::string text);
        void read_profile_cfg(std::vector<std::string> values);
        void read_chirp_cfg(std::vector<std::string> values);
        void read_frame_cfg(std::vector<std::string> values);

        //number of antennas
        int16_t rx_antennas;
        
        //profileCfg configuration
        float profileCfg_chirp_start_freq_GHz;
        float profileCfg_idle_time_us;
        float profileCfg_ramp_end_time_us;
        int16_t profileCfg_adc_samples;
        int16_t profileCfg_adc_sample_rate_ksps;

        //chirpCfg config
        int16_t chirpCfg_start_idx;
        int16_t chirpCfg_end_idx;

        //frame config
        int16_t frameCfg_chirp_start_idx;
        int16_t frameCfg_chirp_end_idx;
        int16_t frameCfG_num_loops;
        float frameCfg_frame_period;

};

#endif
