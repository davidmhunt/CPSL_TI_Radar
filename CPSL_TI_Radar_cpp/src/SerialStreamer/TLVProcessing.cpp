#include "TLVProcessing.hpp"

// Out-of-class definitions: the in-class initializers are declarations only, so
// ODR-use (e.g. binding to a const reference) fails to link in unoptimized builds.
const uint32_t TLVCodes::DETECTED_POINTS;
const uint32_t TLVCodes::RANGE_PROFILE;
const uint32_t TLVCodes::NOISE_PROFILE;
const uint32_t TLVCodes::AZIMUTH_STATIC_HEAT_MAP;
const uint32_t TLVCodes::RANGE_DOPPLER_HEAT_MAP;
const uint32_t TLVCodes::STATS;
const uint32_t TLVCodes::MMWDEMO_OUTPUT_MSG_AZIMUT_ELEVATION_STATIC_HEAT_MAP;
const uint32_t TLVCodes::MMWDEMO_OUTPUT_MSG_TEMPERATURE_STATS;
const uint32_t TLVCodes::DETECTED_POINTS_SIDE_INFO;
const uint32_t TLVCodes::TRACKER;
const uint32_t TLVCodes::RANSAC_FILTER_MASK;
const uint32_t TLVCodes::DETECTED_POINTS_COMPACT;
const uint32_t TLVCodes::SNR_COMPACT;
