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
// start() from Radar::start, acquire()/release() from its DCA worker thread
// (through DCA1000Handler::process_next_packet) and stop() from Radar::stop.
// Nothing here throws.

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
    // most packets one acquire() hands out (DCA1000Handler's batch)
    static constexpr size_t kMaxBatch = 32;

    // one packet, read in place: valid until the release() that covers it
    using PacketView = DCA1000Socket::PacketView;

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
    // Wait at most `timeout` for packets, then hand out up to `max` of them,
    // oldest first, as views that stay valid until release() (design P4: no
    // per-packet copy). 0: none arrived in time. release(n) returns the
    // oldest n acquired packets; call it once per acquire, with its count.
    // The default reads one packet with pop() into a buffer of this object.
    virtual size_t acquire(PacketView* out, size_t max, std::chrono::milliseconds timeout);
    virtual void release(size_t n);

    // packets discarded in user space because the RX ring was full (0 since
    // core-15: a full ring makes the RX thread wait, see ring_full_count())
    virtual uint32_t overrun_count() const { return 0; }
    // times the RX thread found its ring full and stopped reading
    virtual uint32_t ring_full_count() const { return 0; }
    // datagrams the kernel dropped because the socket buffer was full
    virtual uint32_t kernel_drops() const { return 0; }
    // SO_RCVBUF the kernel granted (0 = not a socket)
    virtual size_t rcvbuf_bytes() const { return 0; }

private:
    uint8_t one_[kMaxPacketBytes];  // the default acquire()'s packet
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
    size_t acquire(PacketView* out, size_t max, std::chrono::milliseconds timeout) override;
    void release(size_t n) override;
    uint32_t overrun_count() const override { return socket_.get_overrun_count(); }
    uint32_t ring_full_count() const override { return socket_.get_ring_full_count(); }
    uint32_t kernel_drops() const override { return socket_.get_kernel_drops(); }
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
