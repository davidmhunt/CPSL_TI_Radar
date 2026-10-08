#ifndef RADAR_CONFIG_READER_H
#define RADAR_CONFIG_READER_H

#include <fstream>
#include <string>
#include <iostream>
#include <sstream>
#include <vector>
#include <memory>
#include <cstdint>

#include "BoardDescriptor.hpp"  // cpsl::radar::LvdsStreamFormat

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

        //LVDS stream format (core-24). lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt> <enableSW>, last
        //line wins; -1 / false when the cfg has none. The format a dataFmt carries depends on the firmware
        //(BoardDescriptor::Lvds::stream_formats); the owner sets it, default adc (bytes per frame unchanged).
        int get_lvds_data_fmt() const { return lvds_data_fmt; }
        bool get_lvds_header_enabled() const { return lvds_header_enabled; }
        void set_lvds_stream_format(cpsl::radar::LvdsStreamFormat f) { lvds_stream_format = f; }
        //set the format from the board's (firmware-applied) dataFmt map; a dataFmt it does not map, or no
        //lvdsStreamCfg line, leaves adc (cross_check_radar_cfg rejects an unmapped dataFmt for DCA1000 runs)
        void apply_stream_formats(const cpsl::radar::BoardDescriptor::Lvds& lvds) {
            cpsl::radar::LvdsStreamFormat f = cpsl::radar::LvdsStreamFormat::adc;
            if (lvds_data_fmt < 0 || !lvds.stream_format_for(lvds_data_fmt, f)) f = cpsl::radar::LvdsStreamFormat::adc;
            lvds_stream_format = f;
        }
        cpsl::radar::LvdsStreamFormat get_lvds_stream_format() const { return lvds_stream_format; }
        //adc_sar_meta packet layout (firmware_dev/projects/iwr1843_sar_lvds/docs/lvds_data_format.md section 1):
        //H = 0 (header off) | 64 (rx * samples % 4 == 0) | 56; M = H + 4 * rx * samples; B = M + 64.
        //For adc they describe the plain stream: H = 0, B = M = 4 * rx * samples.
        size_t get_chirp_header_bytes() const;
        size_t get_chirp_adc_end() const;
        size_t get_chirp_packet_bytes() const;
        //realized timing (the CLI's float32 us/ms -> tick conversions, as sar_cfg_check.ticks): chirp cycle
        //Tc = idle + rampEnd in 10 ns ticks, frame period in 5 ns ticks; Tc and Tb = period - Nc * Tc in seconds
        uint32_t get_chirp_cycle_ticks_10ns() const { return idle_ticks_10ns + ramp_end_ticks_10ns; }
        uint32_t get_frame_period_ticks_5ns() const { return frame_period_ticks_5ns; }
        double get_chirp_cycle_s() const;
        double get_frame_blank_s();

        //initialization status
        bool initialized;

        //why the last initialize() failed (empty when it succeeded)
        const std::string& get_error() const { return error; }
    
    private:

        //reading the file
        std::shared_ptr<std::ifstream> cfg_file;

        //functions to read the cfg file: each returns false and sets error
        //on a short line or a value out of range (std::stoi/stof exceptions
        //are caught in process_cfg)
        bool process_cfg();
        std::string error;
        std::vector<std::string> get_vec_from_string(std::string text);
        bool require_fields(const std::vector<std::string>& values, size_t last_field);
        bool read_channel_cfg(const std::vector<std::string>& values);
        bool read_profile_cfg(const std::vector<std::string>& values);
        bool read_chirp_cfg(const std::vector<std::string>& values);
        bool read_frame_cfg(const std::vector<std::string>& values);
        bool read_lvds_stream_cfg(const std::vector<std::string>& values);

        //cfg dialect (board descriptor cfg_dialect)
        std::vector<uint32_t> rx_mask_fields{1};
        uint32_t frame_period_field = 5;

        //number of antennas
        int16_t rx_antennas = 4;
        
        //profileCfg configuration
        float profileCfg_chirp_start_freq_GHz = 0;
        float profileCfg_idle_time_us = 0;
        float profileCfg_ramp_end_time_us = 0;
        int16_t profileCfg_adc_samples = 0;
        int16_t profileCfg_adc_sample_rate_ksps = 0;

        //chirpCfg config
        int16_t chirpCfg_start_idx = 0;
        int16_t chirpCfg_end_idx = 0;

        //frame config
        int16_t frameCfg_chirp_start_idx = 0;
        int16_t frameCfg_chirp_end_idx = 0;
        int16_t frameCfG_num_loops = 0;
        float frameCfg_frame_period = 0;

        //lvdsStreamCfg and the stream format (core-24)
        int lvds_data_fmt = -1;
        bool lvds_header_enabled = false;
        cpsl::radar::LvdsStreamFormat lvds_stream_format = cpsl::radar::LvdsStreamFormat::adc;
        //realized timing ticks (see get_chirp_cycle_ticks_10ns)
        uint32_t idle_ticks_10ns = 0;
        uint32_t ramp_end_ticks_10ns = 0;
        uint32_t frame_period_ticks_5ns = 0;

};

#endif
