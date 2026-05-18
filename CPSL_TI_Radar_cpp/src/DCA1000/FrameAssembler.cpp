#include "FrameAssembler.hpp"
#include <endian.h>
#include <iostream>
#include <algorithm>

void FrameAssembler::configure(size_t bytes_per_frame) {
    bytes_per_frame_ = bytes_per_frame;
    frame_byte_buffer_.assign(bytes_per_frame, 0);
    completed_frame_.assign(bytes_per_frame, 0);
    next_idx_            = 0;
    adc_data_byte_count_ = 0;
    received_packets_    = 0;
    dropped_packets_     = 0;
    dropped_packet_events_ = 0;
}

void FrameAssembler::reset_stats() {
    received_packets_      = 0;
    dropped_packets_       = 0;
    dropped_packet_events_ = 0;
    adc_data_byte_count_   = 0;
}

FrameAssembler::Stats FrameAssembler::get_stats() const {
    return {received_packets_, dropped_packets_, dropped_packet_events_, adc_data_byte_count_};
}

const std::vector<uint8_t>& FrameAssembler::get_frame_bytes() const {
    return completed_frame_;
}

uint32_t FrameAssembler::parse_sequence_number(const uint8_t* data) const {
    uint32_t seq =
        (static_cast<uint32_t>(data[3]) << 24) |
        (static_cast<uint32_t>(data[2]) << 16) |
        (static_cast<uint32_t>(data[1]) <<  8) |
         static_cast<uint32_t>(data[0]);
    return le32toh(seq);
}

uint64_t FrameAssembler::parse_byte_count(const uint8_t* data) const {
    uint64_t bc =
        (static_cast<uint64_t>(data[9]) << 40) |
        (static_cast<uint64_t>(data[8]) << 32) |
        (static_cast<uint64_t>(data[7]) << 24) |
        (static_cast<uint64_t>(data[6]) << 16) |
        (static_cast<uint64_t>(data[5]) <<  8) |
         static_cast<uint64_t>(data[4]);
    return le64toh(bc);
}

void FrameAssembler::finalize_frame() {
    completed_frame_ = frame_byte_buffer_;
    frame_byte_buffer_.assign(bytes_per_frame_, 0);
    next_idx_ = 0;
}

int FrameAssembler::zero_pad(uint64_t target_byte_count) {
    uint64_t bytes_to_fill = target_byte_count - adc_data_byte_count_;
    uint64_t bytes_remaining = bytes_per_frame_ - next_idx_;
    int frames_completed = 0;

    if (bytes_remaining > bytes_to_fill) {
        next_idx_ += bytes_to_fill;
    } else {
        finalize_frame();
        frames_completed = 1;
    }

    adc_data_byte_count_ += bytes_to_fill;
    return frames_completed;
}

int FrameAssembler::push_packet(const uint8_t* data, int len) {
    if (len <= 10) return 0;

    uint32_t seq_num         = parse_sequence_number(data);
    uint64_t packet_byte_count  = parse_byte_count(data);
    uint64_t adc_bytes_in_packet = static_cast<uint64_t>(len) - 10;

    int frames_completed = 0;

    // Detect dropped packets via sequence gap
    if (seq_num != received_packets_ + 1) {
        std::cout << "d-P: " << seq_num << std::endl;
        dropped_packets_       += (seq_num - received_packets_ - 1);
        dropped_packet_events_ += 1;
        frames_completed       += zero_pad(packet_byte_count);
        received_packets_       = seq_num;
    } else {
        received_packets_ += 1;
    }

    // Detect byte-count mismatch (indicates lost data between packets)
    if (adc_data_byte_count_ != packet_byte_count) {
        std::cout << "d-B" << std::endl;
        frames_completed += zero_pad(packet_byte_count);
    } else {
        adc_data_byte_count_ += adc_bytes_in_packet;
    }

    // Copy ADC payload into frame buffer
    const uint8_t* payload = data + 10;
    for (uint64_t i = 0; i < adc_bytes_in_packet; i++) {
        frame_byte_buffer_[next_idx_] = payload[i];
        if (++next_idx_ == bytes_per_frame_) {
            finalize_frame();
            frames_completed++;
        }
    }

    return frames_completed;
}
