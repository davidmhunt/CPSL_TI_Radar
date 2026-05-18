#ifndef DCA1000SOCKET_H
#define DCA1000SOCKET_H

// Manages the two UDP sockets used to communicate with the DCA1000 FPGA board,
// plus a dedicated real-time RX thread that drains the data socket into a
// lock-free ring buffer.
//
// Ring buffer protocol: rx_ring_head_ is written by the RX thread (SCHED_RR 99)
// and read by the worker thread; rx_ring_tail_ is written by the worker and read
// by the RX thread. Both are std::atomic<int> with acquire/release ordering so
// no additional locking is needed in the hot path.
//
// Usage:
//   1. Call init() once to create/bind sockets.
//   2. Call start_rx() when the DCA1000 begins streaming (send_recordStart).
//   3. Call pop_packet() repeatedly from the worker thread to drain frames.
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

    // Pops one packet from the ring buffer (waits up to timeout_ms).
    // Returns false if no packet arrives within the timeout.
    bool pop_packet(uint8_t* buf, int& len, int timeout_ms = 500);

    uint32_t get_overrun_count() const;

    bool is_initialized() const { return initialized_; }

private:
    static constexpr int RX_RING_SIZE = 512;
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
    std::condition_variable rx_ring_cv_;
    std::mutex              rx_ring_cv_mutex_;

    int cmd_socket_  = -1;
    int data_socket_ = -1;

    sockaddr_in cmd_address_{};
    sockaddr_in data_address_{};
    sockaddr_in fpga_address_{};

    bool initialized_ = false;

    void rx_thread_func();
};

#endif // DCA1000SOCKET_H
