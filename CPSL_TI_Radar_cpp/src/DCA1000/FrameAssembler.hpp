#ifndef FRAMEASSEMBLER_H
#define FRAMEASSEMBLER_H

// Assembles raw DCA1000 UDP packets into complete radar frames.
//
// Each call to push_packet() parses the 10-byte DCA1000 header (sequence number
// + byte count), detects dropped packets via sequence gap, zero-pads the frame
// buffer for any missing bytes, then copies the ADC payload into the frame buffer.
// When a complete frame is detected the buffer is latched into completed_frame_
// and push_packet() returns the number of frames completed (typically 1).
//
// Callers must call get_frame_bytes() and consume the result before the next
// push_packet() call that completes a frame — the internal completed_frame_
// buffer is overwritten each time a frame finishes.

#include <vector>
#include <cstdint>
#include <cstddef>

class FrameAssembler {
public:
    struct Stats {
        uint32_t received_packets    = 0;
        uint32_t dropped_packets     = 0;
        uint32_t dropped_packet_events = 0;
        uint64_t adc_data_byte_count = 0;
    };

    void configure(size_t bytes_per_frame);

    // Process one raw DCA1000 UDP packet (includes 10-byte header).
    // Returns the number of frames completed (usually 0 or 1).
    int push_packet(const uint8_t* data, int len);

    // Returns the most recently completed frame buffer (valid after push_packet > 0).
    const std::vector<uint8_t>& get_frame_bytes() const;

    Stats get_stats() const;
    void reset_stats();

private:
    size_t bytes_per_frame_ = 0;
    std::vector<uint8_t> frame_byte_buffer_;
    std::vector<uint8_t> completed_frame_;
    uint64_t next_idx_            = 0;
    uint64_t adc_data_byte_count_ = 0;
    uint32_t received_packets_    = 0;
    uint32_t dropped_packets_     = 0;
    uint32_t dropped_packet_events_ = 0;

    uint32_t parse_sequence_number(const uint8_t* data) const;
    uint64_t parse_byte_count(const uint8_t* data) const;

    // Advance the frame buffer by filling missing bytes with zeros up to target_byte_count.
    // Returns 1 if a frame was completed during padding, 0 otherwise.
    int zero_pad(uint64_t target_byte_count);

    // Latch the current frame buffer into completed_frame_ and reset assembly state.
    void finalize_frame();
};

#endif // FRAMEASSEMBLER_H
