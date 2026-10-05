#ifndef DCA1000_H
#define DCA1000_H

#include <string>
#include <cstdint>
#include <sys/types.h>
#include <atomic>
#include <chrono>
#include <fstream>
#include <vector>
#include <complex>
#include <memory>
#include <mutex>
#include <functional>

#include "SystemConfigReader.hpp"
#include "RadarConfigReader.hpp"
#include "ADCCubeConverter.hpp"
#include "FrameAssembler.hpp"
#include "PacketSource.hpp"

/**
 * @brief The DCA1000 raw-ADC path: packets from a cpsl::radar::PacketSource
 * (the DCA1000 over UDP, or a replay) are assembled into frames
 * (FrameAssembler), converted to the [rx][sample][chirp] cube
 * (ADCCubeConverter), published to the consumer and written to
 * adc_data.bin / LVDS_Raw_0.bin. This class is the only writer of those files.
 */
class DCA1000Handler {
//variables
public:
    //initialization status
    bool initialized;

    bool new_frame_available;

    using Cube = std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>;

    //counters, snapshotted when each frame is published and at stop()
    struct Stats {
        FrameAssembler::Stats assembler;
        uint64_t frames = 0;              //frames completed (and written, when saving)
        uint64_t frames_overwritten = 0;  //published frames replaced before a consumer took them
    };

private:

    //guards adc_data_cube, new_frame_available and the published frame's
    //index/missing/time/stats together (published as one)
    std::mutex frame_mutex;

    //tests only: runs after a frame is converted, before it is published
    std::function<void()> publish_hook_;

    bool output_files_ok_ = true;

    //system configuration information
    SystemConfigReader system_config_reader;

    //radar configuration information
    RadarConfigReader radar_config_reader;

    //where packets come from (UdpPacketSource unless one is given)
    std::shared_ptr<cpsl::radar::PacketSource> source_;

    //processing udp data packets
    size_t udp_packet_size;

    //frame tracking (packet/drop stats are owned by assembler_)
    std::uint32_t received_frames;
    std::uint64_t bytes_per_frame;
    size_t samples_per_chirp;
    size_t chirps_per_frame;
    size_t num_rx_channels;

    //saving to files (output.save_adc_frames / output.save_raw_lvds)
    bool save_adc_frames;
    bool save_raw_lvds;
    std::shared_ptr<std::ofstream> adc_cube_out_file;
    std::shared_ptr<std::ofstream> raw_lvds_out_file;

    //assembling the adc data cube
    //NOTE: indexed by [Rx channel, sample, chirp]
    Cube adc_data_cube;

    //the published frame (under frame_mutex)
    uint64_t latest_index_ = 0;
    size_t latest_missing_ = 0;
    std::chrono::steady_clock::time_point latest_completed_at_{};
    Stats stats_;
    //steady_clock time (ns since its epoch) of the last completed frame; 0 = none yet
    std::atomic<int64_t> last_frame_ns_{0};

    //ADC cube conversion (interleaved / non-interleaved)
    ADCCubeConverter converter_;

    //frame assembly (sequence checking, drop detection, frame buffering)
    FrameAssembler assembler_;

    //processing completed frames
    std::vector<uint8_t> latest_frame_byte_buffer; //most recently captured complete frame byte buffer

//functions
public:
    DCA1000Handler();
    DCA1000Handler( const SystemConfigReader& configReader,
                    const RadarConfigReader& radarConfigReader);
    DCA1000Handler(const DCA1000Handler & rhs) = delete;
    DCA1000Handler & operator=(const DCA1000Handler & rhs) = delete;
    ~DCA1000Handler();

    //configure_pipeline(), then open and configure the packet source
    //(`source`, or a UdpPacketSource on the config's addresses)
    bool initialize(const SystemConfigReader& configReader,
                    const RadarConfigReader& radarConfigReader,
                    std::shared_ptr<cpsl::radar::PacketSource> source = nullptr);

    //configs, output files and frame buffers only: no socket, no DCA1000
    //commands (initialize() starts with it; hardware-free tests use it alone)
    bool configure_pipeline(const SystemConfigReader& configReader,
                            const RadarConfigReader& radarConfigReader);

    //the source process_next_packet() pops from; the caller opens/configures/starts it
    void set_packet_source(std::shared_ptr<cpsl::radar::PacketSource> source);
    const std::shared_ptr<cpsl::radar::PacketSource>& packet_source() const { return source_; }

    //assemble one raw DCA1000 UDP packet (what process_next_packet() pops)
    void ingest_packet(const uint8_t* data, int len);

    //tests only: called between converting a frame and publishing it
    void set_publish_hook(std::function<void()> hook);

    //end of a capture: stop the packet source (UDP: RX thread, then
    //recordStop), then flush and close the output files. Call it after the
    //thread running process_next_packet() has been joined. Idempotent; never throws.
    //Returns false if the source did not stop cleanly or a file failed to flush.
    bool stop();
    //false if flushing/closing an output file failed in stop()
    bool output_files_ok() const { return output_files_ok_; }

    //start the packet source (UDP: recordStart and the RX thread)
    bool send_recordStart();

    //pop one packet (waits up to 500 ms) and ingest it; false if none arrived
    bool process_next_packet();

    //checking for new frame availability
    bool check_new_frame_available();
    Cube get_latest_adc_cube();
    //the published frame, if it is new: copied into `out` with its index,
    //missing (zero-filled) byte count and completion time; clears the flag
    bool take_frame(Cube& out, uint64_t& index, size_t& missing_bytes,
                    std::chrono::steady_clock::time_point& completed_at);
    Stats get_stats();
    //steady_clock time (ns since epoch) of the last completed frame; 0 = none yet
    int64_t last_frame_ns() const { return last_frame_ns_.load(std::memory_order_relaxed); }

private:

    //receiving data / initializing buffers
    void init_buffers();
    void print_status();

    //processing frame byte buffer
    void save_frame_byte_buffer(uint64_t index, size_t missing_bytes);

    //handling files
    bool init_out_file();
    void write_adc_data_cube_to_file();
    bool close_output_files();
};

#endif // DCA1000_H
