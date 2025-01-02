#ifndef TLVPROCESSING
#define TLVPROCESSING

#include <cstdint>
#include <cstring>
#include <vector>
#include <endian.h>

class TLVCodes{
    public:
        static const uint32_t DETECTED_POINTS =1;
        static const uint32_t RANGE_PROFILE =2;
        static const uint32_t NOISE_PROFILE =3;
        static const uint32_t AZIMUTH_STATIC_HEAT_MAP =4;
        static const uint32_t RANGE_DOPPLER_HEAT_MAP =5;
        static const uint32_t STATS =6;
        static const uint32_t STMMWDEMO_OUTPUT_MSG_DETECTED_POINTS_SIDE_INFOATS =7;
        static const uint32_t MMWDEMO_OUTPUT_MSG_AZIMUT_ELEVATION_STATIC_HEAT_MAP =8;
        static const uint32_t MMWDEMO_OUTPUT_MSG_TEMPERATURE_STATS =9;
};

class TLVDetectedPoints{
    
    //constructors, destructors, assignment operators
    public:
        TLVDetectedPoints();
        TLVDetectedPoints(const TLVDetectedPoints & rhs);
        TLVDetectedPoints & operator=(const TLVDetectedPoints & rhs);
        ~TLVDetectedPoints();

        bool valid_data;
    public:
        std::vector<std::vector<float>> detected_points;

        void process(
            std::vector<uint8_t> & tlv_raw_data_bytes
        );

        //helper function
        std::vector<float> bytes_to_floats(
            std::vector<uint8_t> & bytes
        );
};



#endif