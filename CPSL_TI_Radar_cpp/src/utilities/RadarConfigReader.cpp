#include "RadarConfigReader.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <exception>

#include "Log.hpp"

/**
 * @brief default constructor without initialization
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

RadarConfigReader::RadarConfigReader(const std::string& filename,
                                     const std::vector<uint32_t>& rx_mask_fields_in,
                                     uint32_t frame_period_field_in):
    initialized(false),
    cfg_file(nullptr)
{
    initialize(filename, rx_mask_fields_in, frame_period_field_in);
}

RadarConfigReader::RadarConfigReader(const RadarConfigReader & rhs):
    initialized(rhs.initialized),
    cfg_file(rhs.cfg_file),
    error(rhs.error),
    rx_mask_fields(rhs.rx_mask_fields),
    frame_period_field(rhs.frame_period_field),
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
    frameCfg_frame_period(rhs.frameCfg_frame_period),
    lvds_data_fmt(rhs.lvds_data_fmt),
    lvds_header_enabled(rhs.lvds_header_enabled),
    lvds_stream_format(rhs.lvds_stream_format),
    idle_ticks_10ns(rhs.idle_ticks_10ns),
    ramp_end_ticks_10ns(rhs.ramp_end_ticks_10ns),
    frame_period_ticks_5ns(rhs.frame_period_ticks_5ns)
{}

/**
 * @brief Assignment operator
 * 
 * @param rhs 
 * @return RadarConfigReader& 
 */
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
        error = rhs.error;
        rx_mask_fields = rhs.rx_mask_fields;
        frame_period_field = rhs.frame_period_field;
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
        lvds_data_fmt = rhs.lvds_data_fmt;
        lvds_header_enabled = rhs.lvds_header_enabled;
        lvds_stream_format = rhs.lvds_stream_format;
        idle_ticks_10ns = rhs.idle_ticks_10ns;
        ramp_end_ticks_10ns = rhs.ramp_end_ticks_10ns;
        frame_period_ticks_5ns = rhs.frame_period_ticks_5ns;
    }

    return *this;
}

/**
 * @brief Destroy the Radar Config Reader:: Radar Config Reader object
 * 
 */
RadarConfigReader::~RadarConfigReader()
{   
    if (cfg_file.get() != nullptr &&
        cfg_file.use_count() == 1 &&
        cfg_file -> is_open()){
            cfg_file -> close();
        }
}

/**
 * @brief Initialize the radar configuration reader
 * 
 * @param filename path to a .cfg file used to configure a TI radar
 */
void RadarConfigReader::initialize(const std::string & filename){
    initialize(filename, std::vector<uint32_t>{1}, 5);
}

void RadarConfigReader::initialize(const std::string & filename,
                                   const std::vector<uint32_t> & rx_mask_fields_in,
                                   uint32_t frame_period_field_in){

    rx_mask_fields = rx_mask_fields_in;
    frame_period_field = frame_period_field_in;

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
        cpsl::radar::log_debug("RadarConfigReader: error opening file: ", filename);  //get_error() has it
        error = "cannot open " + filename;
        initialized = false;
    } else{

        //defaults before parsing (rx 4 is kept if channelCfg is absent from the .cfg);
        //nothing from an earlier initialize() survives
        rx_antennas = 4;
        profileCfg_chirp_start_freq_GHz = 0;
        profileCfg_idle_time_us = 0;
        profileCfg_ramp_end_time_us = 0;
        profileCfg_adc_samples = 0;
        profileCfg_adc_sample_rate_ksps = 0;
        chirpCfg_start_idx = 0;
        chirpCfg_end_idx = 0;
        frameCfg_chirp_start_idx = 0;
        frameCfg_chirp_end_idx = 0;
        frameCfG_num_loops = 0;
        frameCfg_frame_period = 0;
        lvds_data_fmt = -1;
        lvds_header_enabled = false;
        lvds_stream_format = cpsl::radar::LvdsStreamFormat::adc;
        idle_ticks_10ns = 0;
        ramp_end_ticks_10ns = 0;
        frame_period_ticks_5ns = 0;

        //process the configuration
        error.clear();
        if (!process_cfg()) {
            cpsl::radar::log_debug("RadarConfigReader: ", filename, ": ", error);  //get_error() has it
            initialized = false;
            return;
        }

        cpsl::radar::log_debug("[RadarConfig] rx_antennas: ", rx_antennas);

        initialized = true;
    }
}

/**
 * @brief Get the number of bytes used to transmit a frame's
 * worth of raw radar adc data
 * 
 * @return size_t the number of bytes in a given frame
 */
size_t RadarConfigReader::get_bytes_per_frame(){

    //number of chirps per frame
    const size_t chirps_per_frame = static_cast<size_t>(get_chirps_per_frame());

    //adc: 4 bytes per complex sample, packed; adc_sar_meta: one packet of B bytes per chirp (core-24)
    if (lvds_stream_format == cpsl::radar::LvdsStreamFormat::adc_sar_meta) {
        return get_chirp_packet_bytes() * chirps_per_frame;
    }

    //number of bytes per sample (assuming complex samples)
    size_t bytes_per_sample = 4;

    return bytes_per_sample * 
        static_cast<size_t>(rx_antennas) * 
        static_cast<size_t>(profileCfg_adc_samples) * 
        chirps_per_frame;

}

size_t RadarConfigReader::get_chirp_header_bytes() const {
    if (lvds_stream_format != cpsl::radar::LvdsStreamFormat::adc_sar_meta || !lvds_header_enabled) return 0;
    const size_t rs = static_cast<size_t>(rx_antennas) * static_cast<size_t>(profileCfg_adc_samples);
    return rs % 4 == 0 ? 64 : 56;
}

size_t RadarConfigReader::get_chirp_adc_end() const {
    return get_chirp_header_bytes() +
           4 * static_cast<size_t>(rx_antennas) * static_cast<size_t>(profileCfg_adc_samples);
}

size_t RadarConfigReader::get_chirp_packet_bytes() const {
    return get_chirp_adc_end() + (lvds_stream_format == cpsl::radar::LvdsStreamFormat::adc_sar_meta ? 64 : 0);
}

double RadarConfigReader::get_chirp_cycle_s() const {
    //sar_cfg_check: tc_us = tc_t / 100.0; tc_s = tc_us * 1e-6
    return (static_cast<double>(get_chirp_cycle_ticks_10ns()) / 100.0) * 1e-6;
}

double RadarConfigReader::get_frame_blank_s() {
    //sar_cfg_check: tb_us = period_t * 5 / 1000.0 - nc * tc_us; tb_s = tb_us * 1e-6
    const double tc_us = static_cast<double>(get_chirp_cycle_ticks_10ns()) / 100.0;
    const double period_us = static_cast<double>(frame_period_ticks_5ns) * 5 / 1000.0;
    return (period_us - static_cast<double>(get_chirps_per_frame()) * tc_us) * 1e-6;
}

/**
 * @brief Get the number of chirps per frame of radar data
 * 
 * @return size_t 
 */
size_t RadarConfigReader::get_chirps_per_frame(){
    return static_cast<size_t>(frameCfg_chirp_end_idx - frameCfg_chirp_start_idx + 1) * frameCfG_num_loops;
}

/**
 * @brief Get the number of I-Q Samples in a given chirp
 * 
 * @return size_t 
 */
size_t RadarConfigReader::get_samples_per_chirp(){
    return static_cast<size_t>(profileCfg_adc_samples);
}

size_t RadarConfigReader::get_num_rx_antennas(){
    return static_cast<size_t>(rx_antennas);
}

/**
 * @brief Get the frame period from frameCfg
 *
 * @return float the frame period in milliseconds
 */
float RadarConfigReader::get_frame_period_ms(){
    return frameCfg_frame_period;
}

/**
 * @brief Process a new cfg file (cfg_file path must already
 * be defined)
 * 
 */
bool RadarConfigReader::process_cfg() {

    if(cfg_file.get() == nullptr || !cfg_file -> is_open()){
        error = "cfg file isn't open";
        return false;
    }

    bool have_profile = false, have_frame = false;
    std::string line;
    size_t line_no = 0;
    while (std::getline(*cfg_file, line)) {
        line_no++;
        std::istringstream iss(line);
        std::string key;
        if (!std::getline(iss, key, ' ')) continue;
        if (key != "channelCfg" && key != "profileCfg" && key != "chirpCfg" && key != "frameCfg" &&
            key != "lvdsStreamCfg") continue;

        const std::vector<std::string> values = get_vec_from_string(line);
        bool ok = false;
        try {
            if (key == "channelCfg") ok = read_channel_cfg(values);
            else if (key == "profileCfg") ok = have_profile = read_profile_cfg(values);
            else if (key == "chirpCfg") ok = read_chirp_cfg(values);
            else if (key == "lvdsStreamCfg") ok = read_lvds_stream_cfg(values);
            else ok = have_frame = read_frame_cfg(values);
        } catch (const std::exception&) {
            //std::stoi / std::stof: not a number, or out of range
            error = key + " has a field that is not a valid number";
            ok = false;
        }
        if (!ok) {
            error = "line " + std::to_string(line_no) + ": " + error;
            return false;
        }
    }

    if (!have_profile) {
        error = "no profileCfg line (samples per chirp unknown)";
        return false;
    }
    if (!have_frame) {
        error = "no frameCfg line (chirps per frame and frame period unknown)";
        return false;
    }
    return true;
}

/**
 * @brief Get a vector of strings from a given string. String
 * is separated using ' ' characters.
 * 
 * @param text a std::string object
 * @return std::vector<std::string> the vector of strings
 */
std::vector<std::string> RadarConfigReader::get_vec_from_string(std::string text)
{
    std::istringstream iss(text);
    std::string value;
    std::vector<std::string> values;
    while (iss >> value)
    {
        values.push_back(value);
    }  

    return values;
}

// true if the line has fields 1..last_field; otherwise sets error
bool RadarConfigReader::require_fields(const std::vector<std::string>& values, size_t last_field){
    if (values.size() > last_field) return true;
    error = values[0] + " has " + std::to_string(values.size() - 1) + " fields, needs at least " +
            std::to_string(last_field);
    return false;
}

namespace {

//the TI CLI's us/ms -> LSB conversion, (uint32_t)((float)atof(x) * mult / div), in float32 (as
//firmware_dev/projects/iwr1843_sar_lvds/tools/sar_cfg_check.py ticks())
uint32_t cli_ticks(const std::string& tok, float mult, float div) {
    const float v = static_cast<float>(std::atof(tok.c_str()));
    const float a = v * mult;
    const float b = a / div;
    return b > 0.0f ? static_cast<uint32_t>(b) : 0u;
}

}  // namespace

/**
 * @brief Decode the profile configuration from the profile cfg
 * 
 * @param values std::vector<std::string>> vector of strings from the corresponding cfg file line
 */
bool RadarConfigReader::read_profile_cfg(const std::vector<std::string>& values){

    if (!require_fields(values, 11)) return false;

    //set the profile config
    profileCfg_chirp_start_freq_GHz = std::stof(values[2]);
    profileCfg_idle_time_us = std::stof(values[3]);
    profileCfg_ramp_end_time_us = std::stof(values[5]);
    idle_ticks_10ns = cli_ticks(values[3], 1000.0f, 10.0f);
    ramp_end_ticks_10ns = cli_ticks(values[5], 1000.0f, 10.0f);
    const int samples = std::stoi(values[10]);
    if (samples < 1 || samples > INT16_MAX) {
        error = "profileCfg numAdcSamples " + values[10] + " is out of range";
        return false;
    }
    profileCfg_adc_samples = static_cast<int16_t>(samples);
    profileCfg_adc_sample_rate_ksps = static_cast<int16_t>(std::stoi(values[11]));
    return true;
}

/**
 * @brief Decode the chirp configuration from the profile cfg
 * 
 * @param values std::vector<std::string>> vector of strings from the corresponding cfg file line
 */
bool RadarConfigReader::read_chirp_cfg(const std::vector<std::string>& values){

    if (!require_fields(values, 2)) return false;

    //set the chirp config
    chirpCfg_start_idx = static_cast<int16_t>(std::stoi(values[1]));
    chirpCfg_end_idx = static_cast<int16_t>(std::stoi(values[2]));
    return true;
}

/**
 * @brief Decode the frame configuration from the profile cfg
 *
 * @param values std::vector<std::string>> vector of strings from the corresponding cfg file line
 */
bool RadarConfigReader::read_frame_cfg(const std::vector<std::string>& values){

    //fields 1-3 and the dialect's period field must exist
    const size_t needed = std::max<size_t>(4, static_cast<size_t>(frame_period_field) + 1);
    if (values.size() < needed) {
        error = "frameCfg has " + std::to_string(values.size() - 1) + " fields, needs at least " +
                std::to_string(needed - 1) + " (frame period in field " + std::to_string(frame_period_field) + ")";
        return false;
    }

    //set the frame config
    const int start = std::stoi(values[1]);
    const int end = std::stoi(values[2]);
    const int loops = std::stoi(values[3]);
    if (start < 0 || end < start || end > INT16_MAX || loops < 1 || loops > INT16_MAX) {
        error = "frameCfg chirp range " + values[1] + ".." + values[2] + " x " + values[3] +
                " loops is not a valid frame";
        return false;
    }
    frameCfg_chirp_start_idx = static_cast<int16_t>(start);
    frameCfg_chirp_end_idx = static_cast<int16_t>(end);
    frameCfG_num_loops = static_cast<int16_t>(loops);

    //the period's field comes from the board's cfg dialect: 5 on the single-chip
    //SDK demos, 6 on the AWR2243 cascade (mmWave MCU+ SDK), which inserts
    //<numAdcSamples> before it:
    //frameCfg <start> <end> <loops> <frames> <adcSamples> <periodMs> <trigger> <delay> <...>
    frameCfg_frame_period = std::stof(values[frame_period_field]);
    frame_period_ticks_5ns = cli_ticks(values[frame_period_field], 1000000.0f, 5.0f);
    return true;
}

/**
 * @brief Decode lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt> <enableSW> (core-24); a later line
 * replaces an earlier one, as on the CLI
 */
bool RadarConfigReader::read_lvds_stream_cfg(const std::vector<std::string>& values){
    //never fails the load (it did not before core-24): a short or non-numeric line is left to
    //cross_check_radar_cfg, which reports it when the DCA1000 stream is enabled
    if (values.size() < 4) return true;
    char* end1 = nullptr;
    char* end2 = nullptr;
    const long hdr = std::strtol(values[2].c_str(), &end1, 10);
    const long fmt = std::strtol(values[3].c_str(), &end2, 10);
    if (*end1 != '\0' || *end2 != '\0' || end1 == values[2].c_str() || end2 == values[3].c_str()) return true;
    lvds_header_enabled = hdr != 0;
    lvds_data_fmt = static_cast<int>(fmt);
    return true;
}

/**
 * @brief Decode the channel configuration. Sets rx_antennas by counting
 * set bits in the Rx channel bitmask fields named by the board's cfg dialect.
 * Format: channelCfg <rxMask> <txMask> <cascading>                      (fields [1])
 * Cascade format: channelCfg <rxMaskMaster> <txMaskMaster> <cascading> <rxMaskSlave> <txMaskSlave>
 *                                                                       (fields [1, 4])
 * A listed field past the end of the line is not counted.
 *
 * @param values std::vector<std::string>> vector of strings from the corresponding cfg file line
 */
bool RadarConfigReader::read_channel_cfg(const std::vector<std::string>& values){
    int rx = 0;
    for (uint32_t field : rx_mask_fields) {
        if (field < values.size()) {
            rx += __builtin_popcount(static_cast<unsigned>(std::stoi(values[field])));
        }
    }
    rx_antennas = static_cast<int16_t>(rx);
    return true;
}
