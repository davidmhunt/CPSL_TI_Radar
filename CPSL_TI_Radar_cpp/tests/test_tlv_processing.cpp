// TLVProcessing: the TLV type codes. The payload decoders are tested through
// parse_uart_frame (test_serial_streamer_frames, test_uart_parse).
#include "test_harness.hpp"
#include "TLVProcessing.hpp"

TEST_CASE(tlv_code_values) {
    CHECK_EQ(TLVCodes::DETECTED_POINTS, 1u);
    CHECK_EQ(TLVCodes::RANGE_PROFILE, 2u);
    CHECK_EQ(TLVCodes::DETECTED_POINTS_SIDE_INFO, 7u);
    CHECK_EQ(TLVCodes::TRACKER, 10u);
    CHECK_EQ(TLVCodes::RANSAC_FILTER_MASK, 11u);
    CHECK_EQ(TLVCodes::DETECTED_POINTS_COMPACT, 12u);  // was 104 (a guess) before core-16
    CHECK_EQ(TLVCodes::SNR_COMPACT, 13u);
}

TEST_MAIN()
