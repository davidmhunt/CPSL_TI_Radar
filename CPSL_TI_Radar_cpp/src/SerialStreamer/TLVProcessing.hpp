#ifndef TLVPROCESSING
#define TLVPROCESSING

// TLV type codes of the TI demos' serial frames. The decoders are in
// UartFrame.cpp (parse_uart_frame); only types 1 and 7 are decoded, every
// other type is skipped by its length.

#include <cstdint>

class TLVCodes{
    public:
        static const uint32_t DETECTED_POINTS =1;
        static const uint32_t RANGE_PROFILE =2;
        static const uint32_t NOISE_PROFILE =3;
        static const uint32_t AZIMUTH_STATIC_HEAT_MAP =4;
        static const uint32_t RANGE_DOPPLER_HEAT_MAP =5;
        static const uint32_t STATS =6;
        static const uint32_t MMWDEMO_OUTPUT_MSG_AZIMUT_ELEVATION_STATIC_HEAT_MAP =8;
        static const uint32_t MMWDEMO_OUTPUT_MSG_TEMPERATURE_STATS =9;
        static const uint32_t DETECTED_POINTS_SIDE_INFO =7;
        //AWR2243 cascade (AM273x MCU+) demo, firmware_dev mmw_output.h
        static const uint32_t TRACKER =10;
        static const uint32_t RANSAC_FILTER_MASK =11;
        static const uint32_t DETECTED_POINTS_COMPACT =12;
        static const uint32_t SNR_COMPACT =13;
};

#endif
