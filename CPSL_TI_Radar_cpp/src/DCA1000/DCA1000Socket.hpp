#ifndef DCA1000SOCKET_H
#define DCA1000SOCKET_H

// Manages the two UDP sockets used to communicate with the DCA1000 FPGA board,
// plus a dedicated real-time RX thread that drains the data socket into a
// lock-free ring buffer, up to kRecvBatch datagrams per recvmmsg() call,
// received straight into the ring slots.
//
// Ring buffer protocol (single producer, single consumer): rx_ring_head_ is
// written by the RX thread and read by the worker thread; rx_ring_tail_ is
// written by the worker and read by the RX thread. The worker reads packets
// in place (acquire_packets() returns views into the ring slots, no copy) and
// hands the slots back with release_packets(). Neither side takes a lock in
// the hot path: the RX thread notifies the worker's condition variable only
// when the worker has said it is about to sleep (worker_waiting_), so a
// busy worker costs no futex call per packet (design P4).
//
// Usage:
//   1. Call init() once to create/bind sockets.
//   2. Call start_rx() when the DCA1000 begins streaming (send_recordStart).
//   3. Call acquire_packets() / release_packets() repeatedly from the worker
//      thread (or pop_packet(), which copies one packet out).
//   4. Call stop_rx() to join the RX thread (before send_recordStop).

#include <string>
#include <vector>
#include <array>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <cstdint>
#include <cstddef>
#include <sys/socket.h>
#include <arpa/inet.h>

class DCA1000Socket {
public:
    DCA1000Socket();
    ~DCA1000Socket();

    // Creates and binds cmd and data sockets. Configures SO_RCVBUF and timeouts.
    bool init(const std::string& fpga_ip, const std::string& system_ip,
              int cmd_port, int data_port,
              size_t rcvbuf_bytes = 64 * 1024 * 1024);

    // Resets the ring buffer and spawns the SCHED_RR 99 RX thread.
    void start_rx();

    // Signals the RX thread to exit and joins it.
    void stop_rx();

    // Sends a command packet to the FPGA via the cmd socket.
    bool send_command(std::vector<uint8_t>& cmd);

    // Receives a response from the FPGA on the cmd socket.
    bool receive_response(std::vector<uint8_t>& buffer);

    // One received packet, in place in the ring.
    struct PacketView {
        const uint8_t* data;
        int len;
    };

    // Waits up to timeout_ms for at least one packet, then returns up to
    // `max` of the oldest unreleased packets as views into the ring, in
    // order. The views stay valid until release_packets(). 0: none arrived.
    // Worker thread only.
    int acquire_packets(PacketView* out, int max, int timeout_ms = 500);

    // Hands the oldest `n` acquired packets' slots back to the RX thread.
    void release_packets(int n);

    // Copies one packet out of the ring (acquire + copy + release).
    // Returns false if no packet arrives within the timeout.
    bool pop_packet(uint8_t* buf, int& len, int timeout_ms = 500);

    uint32_t get_overrun_count() const;

    // SO_RCVBUF the kernel granted in init() (0 before init)
    size_t get_granted_rcvbuf() const { return granted_rcvbuf_; }

    bool is_initialized() const { return initialized_; }

private:
    static constexpr int RX_RING_SIZE = 512;
    // datagrams one recvmmsg() call may take (design P5)
    static constexpr int kRecvBatch = 32;
    struct RxSlot {
        std::array<uint8_t, 1472> data;
        int bytes_received;
    };

    std::array<RxSlot, RX_RING_SIZE> rx_ring_;
    std::atomic<int>      rx_ring_head_;
    std::atomic<int>      rx_ring_tail_;
    std::atomic<uint32_t> rx_overrun_count_;
    std::atomic<bool>     rx_thread_running_;
    std::thread           rx_thread_;
    // the worker sleeps on rx_ring_cv_ only after setting worker_waiting_
    // (seq_cst), and the RX thread reads it (seq_cst) after publishing a new
    // head, so either the worker sees the packet or the RX thread sees the
    // flag and notifies
    std::atomic<bool>       worker_waiting_;
    std::condition_variable rx_ring_cv_;
    std::mutex              rx_ring_cv_mutex_;

    int cmd_socket_  = -1;
    int data_socket_ = -1;

    sockaddr_in cmd_address_{};
    sockaddr_in data_address_{};
    sockaddr_in fpga_address_{};

    bool initialized_ = false;
    size_t granted_rcvbuf_ = 0;

    void rx_thread_func();
};

#endif // DCA1000SOCKET_H
