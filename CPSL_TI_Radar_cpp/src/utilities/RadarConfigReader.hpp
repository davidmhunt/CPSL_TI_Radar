#ifndef RADAR_CONFIG_READER_H
#define RADAR_CONFIG_READER_H

#include <fstream>
#include <string>
#include <iostream>
#include <sstream>
#include <vector>
#include <memory>
#include <cstdint>

class RadarConfigReader{
    public:
        RadarConfigReader();
        RadarConfigReader(const std::string& filename);
        RadarConfigReader(const std::string& filename,
                          const std::vector<uint32_t>& rx_mask_fields,
                          uint32_t frame_period_field);
        RadarConfigReader(const RadarConfigReader & rhs);
        RadarConfigReader & operator=(const RadarConfigReader & rhs);
        ~RadarConfigReader();

        //functions to initialize the radar config reader
        //rx_mask_fields / frame_period_field: the board descriptor's cfg_dialect
        //(channelCfg fields whose set bits are summed into the Rx count, frameCfg
        //field holding the period; the command word is field 0). The one-argument
        //form uses the single-chip default {1} / 5.
        void initialize(const std::string & filename);
        void initialize(const std::string & filename,
                        const std::vector<uint32_t> & rx_mask_fields,
                        uint32_t frame_period_field);

        //functions to get specific variables
        size_t get_bytes_per_frame();
        size_t get_chirps_per_frame();
        size_t get_samples_per_chirp();
        size_t get_num_rx_antennas();
        float get_frame_period_ms();

        //initialization status
        bool initialized;

        //why the last initialize() failed (empty when it succeeded or the file was missing)
        const std::string& get_error() const { return error; }
    
    private:

        //reading the file
        std::shared_ptr<std::ifstream> cfg_file;

        //functions to read the cfg file
        bool process_cfg();
        std::string error;
        std::vector<std::string> get_vec_from_string(std::string text);
        void read_channel_cfg(std::vector<std::string> values);
        void read_profile_cfg(std::vector<std::string> values);
        void read_chirp_cfg(std::vector<std::string> values);
        bool read_frame_cfg(std::vector<std::string> values);

        //cfg dialect (board descriptor cfg_dialect)
        std::vector<uint32_t> rx_mask_fields{1};
        uint32_t frame_period_field = 5;

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
