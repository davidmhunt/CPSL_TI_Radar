#ifndef CPSL_RADAR_PACKET_SOURCE_HPP
#define CPSL_RADAR_PACKET_SOURCE_HPP

// PacketSource: where raw DCA1000 packets come from (driver v2 design §3
// "Internal seams for tests"; directive core-13). A packet is the DCA1000's
// UDP datagram: 10-byte header (sequence number, byte count) + ADC payload,
// at most kMaxPacketBytes.
//
//   UdpPacketSource     the DCA1000 itself: two UDP sockets, the FPGA command
//                       protocol (DCA1000Commands) and the SCHED_RR RX thread
//                       (DCA1000Socket)
//   ReplayPacketSource  packets held in memory (tests, offline replay)
//
// Radar calls open() from Radar::open, configure() from Radar::configure,
// start() from Radar::start, pop() from its DCA worker thread and stop() from
// Radar::stop. Nothing here throws.

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <chrono>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

#include "DCA1000Socket.hpp"
#include "Status.hpp"
#include "SystemConfigReader.hpp"

namespace cpsl {
namespace radar {

class PacketSource {
public:
    static constexpr size_t kMaxPacketBytes = 1472;

    virtual ~PacketSource() = default;

    // Open the transport (UDP: create and bind the sockets).
    virtual Status open() = 0;
    // Prepare the capture device for a run (UDP: connect, reset, packet
    // size/delay, LVDS mode, FPGA version).
    virtual Status configure() = 0;
    // Start delivering packets (UDP: recordStart, then the RX thread).
    virtual Status start() = 0;
    // Stop delivering packets (UDP: join the RX thread, then recordStop).
    // Idempotent. A non-ok Status is a warning: nothing is left open.
    virtual Status stop() = 0;
    // Wait at most `timeout` for one packet; copy it to `buf` (at least
    // kMaxPacketBytes) and set `len`. false: none arrived in time.
    virtual bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) = 0;

    // packets discarded because the RX ring was full
    virtual uint32_t overrun_count() const { return 0; }
    // SO_RCVBUF the kernel granted (0 = not a socket)
    virtual size_t rcvbuf_bytes() const { return 0; }
};

// The DCA1000 over UDP, with the addresses, ports and board LVDS settings of
// a loaded system config.
class UdpPacketSource : public PacketSource {
public:
    explicit UdpPacketSource(const SystemConfigReader& config);

    Status open() override;
    Status configure() override;
    Status start() override;
    Status stop() override;
    bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) override;
    uint32_t overrun_count() const override { return socket_.get_overrun_count(); }
    size_t rcvbuf_bytes() const override { return socket_.get_granted_rcvbuf(); }

    // FPGA commands (each true when the DCA1000 answered with status 0)
    bool send_systemConnect();
    bool send_resetFPGA();
    bool send_configPacketData(size_t packet_size, uint16_t delay_us);
    bool send_configFPGAGen();
    float send_readFPGAVersion();  // 0 when there was no answer
    bool send_recordStart();
    bool send_recordStop();

private:
    bool command(std::vector<uint8_t> cmd, uint16_t* status_out = nullptr);

    SystemConfigReader config_;
    DCA1000Socket socket_;
    bool started_ = false;
};

// Packets from memory. Packets pushed before start() wait until start();
// after that pop() returns them in order, then times out (as a quiet DCA1000
// would). Thread-safe.
class ReplayPacketSource : public PacketSource {
public:
    ReplayPacketSource() = default;
    explicit ReplayPacketSource(std::vector<std::vector<uint8_t>> packets);

    void push(std::vector<uint8_t> packet);

    Status open() override { return Status::ok(); }
    Status configure() override { return Status::ok(); }
    Status start() override;
    Status stop() override;
    bool pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) override;

    size_t remaining() const;
    bool started() const;

private:
    mutable std::mutex m_;
    std::condition_variable cv_;
    std::deque<std::vector<uint8_t>> queue_;
    bool started_ = false;
};

}  // namespace radar
}  // namespace cpsl

#endif
