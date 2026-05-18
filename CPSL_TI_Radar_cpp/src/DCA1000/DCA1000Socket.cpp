#include "DCA1000Socket.hpp"
#include <iostream>
#include <cstring>
#include <unistd.h>
#include <pthread.h>
#include <sched.h>
#include <algorithm>

DCA1000Socket::DCA1000Socket()
    : rx_ring_(),
      rx_ring_head_(0),
      rx_ring_tail_(0),
      rx_overrun_count_(0),
      rx_thread_running_(false)
{}

DCA1000Socket::~DCA1000Socket() {
    stop_rx();
    if (cmd_socket_ >= 0)  { close(cmd_socket_);  cmd_socket_  = -1; }
    if (data_socket_ >= 0) { close(data_socket_); data_socket_ = -1; }
}

bool DCA1000Socket::init(const std::string& fpga_ip, const std::string& system_ip,
                         int cmd_port, int data_port, size_t rcvbuf_bytes)
{
    // Build address structures
    cmd_address_.sin_family      = AF_INET;
    cmd_address_.sin_addr.s_addr = inet_addr(system_ip.c_str());
    cmd_address_.sin_port        = htons(static_cast<uint16_t>(cmd_port));

    data_address_.sin_family      = AF_INET;
    data_address_.sin_addr.s_addr = inet_addr(system_ip.c_str());
    data_address_.sin_port        = htons(static_cast<uint16_t>(data_port));

    fpga_address_.sin_family      = AF_INET;
    fpga_address_.sin_addr.s_addr = inet_addr(fpga_ip.c_str());
    fpga_address_.sin_port        = htons(static_cast<uint16_t>(cmd_port));

    // Create sockets
    cmd_socket_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (cmd_socket_ < 0) {
        std::cerr << "Failed to create cmd socket" << std::endl;
        return false;
    }

    data_socket_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (data_socket_ < 0) {
        std::cerr << "Failed to create data socket" << std::endl;
        return false;
    }

    // cmd socket timeout: 2 s for command/response latency
    struct timeval cmd_timeout;
    cmd_timeout.tv_sec  = 2;
    cmd_timeout.tv_usec = 0;
    setsockopt(cmd_socket_, SOL_SOCKET, SO_RCVTIMEO, &cmd_timeout, sizeof(cmd_timeout));

    // data socket timeout: 500 ms — exits promptly when DCA1000 stops streaming
    struct timeval data_timeout;
    data_timeout.tv_sec  = 0;
    data_timeout.tv_usec = 500000;
    setsockopt(data_socket_, SOL_SOCKET, SO_RCVTIMEO, &data_timeout, sizeof(data_timeout));

    // Request large receive buffer to absorb bursts at high ADC rates
    int rcvbuf = static_cast<int>(rcvbuf_bytes);
    setsockopt(data_socket_, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));
    int actual_rcvbuf = 0;
    socklen_t optlen = sizeof(actual_rcvbuf);
    getsockopt(data_socket_, SOL_SOCKET, SO_RCVBUF, &actual_rcvbuf, &optlen);
    std::cout << "[DCA1000] SO_RCVBUF granted: " << actual_rcvbuf << " bytes" << std::endl;

    // Bind sockets
    if (bind(cmd_socket_, reinterpret_cast<struct sockaddr*>(&cmd_address_),
             sizeof(cmd_address_)) < 0) {
        std::cerr << "Failed to bind cmd socket" << std::endl;
        close(cmd_socket_); cmd_socket_ = -1;
        return false;
    }
    std::cout << "Bound to command socket" << std::endl;

    if (bind(data_socket_, reinterpret_cast<struct sockaddr*>(&data_address_),
             sizeof(data_address_)) < 0) {
        std::cerr << "Failed to bind data socket" << std::endl;
        close(data_socket_); data_socket_ = -1;
        return false;
    }
    std::cout << "Bound to data socket" << std::endl;

    initialized_ = true;
    return true;
}

void DCA1000Socket::start_rx() {
    rx_ring_head_.store(0, std::memory_order_relaxed);
    rx_ring_tail_.store(0, std::memory_order_relaxed);
    rx_overrun_count_.store(0, std::memory_order_relaxed);
    rx_thread_running_.store(true, std::memory_order_relaxed);
    rx_thread_ = std::thread(&DCA1000Socket::rx_thread_func, this);
    struct sched_param sp;
    sp.sched_priority = 99;
    if (pthread_setschedparam(rx_thread_.native_handle(), SCHED_RR, &sp) != 0) {
        std::cerr << "[DCA1000] Warning: could not set RX thread to SCHED_RR 99 "
                  << "(run as root or grant cap_sys_nice)" << std::endl;
    }
}

void DCA1000Socket::stop_rx() {
    rx_thread_running_.store(false, std::memory_order_relaxed);
    if (rx_thread_.joinable()) rx_thread_.join();
}

bool DCA1000Socket::send_command(std::vector<uint8_t>& cmd) {
    if (cmd_socket_ < 0) {
        std::cerr << "cmd socket not bound" << std::endl;
        return false;
    }
    ssize_t sent = sendto(cmd_socket_, cmd.data(), cmd.size(), 0,
                          reinterpret_cast<struct sockaddr*>(&fpga_address_),
                          sizeof(fpga_address_));
    if (sent != static_cast<ssize_t>(cmd.size())) {
        std::cerr << "Failed to send command" << std::endl;
        return false;
    }
    return true;
}

bool DCA1000Socket::receive_response(std::vector<uint8_t>& buffer) {
    if (cmd_socket_ < 0) {
        std::cerr << "cmd socket not bound" << std::endl;
        return false;
    }
    struct sockaddr_in from{};
    socklen_t from_len = sizeof(from);
    ssize_t n = recvfrom(cmd_socket_, buffer.data(), buffer.size(), 0,
                         reinterpret_cast<struct sockaddr*>(&from), &from_len);
    if (n < 0) {
        std::cerr << "Failed to receive response" << std::endl;
        return false;
    }
    return true;
}

bool DCA1000Socket::pop_packet(uint8_t* buf, int& len, int timeout_ms) {
    {
        std::unique_lock<std::mutex> lock(rx_ring_cv_mutex_);
        rx_ring_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms), [this] {
            return rx_ring_head_.load(std::memory_order_acquire) !=
                   rx_ring_tail_.load(std::memory_order_relaxed);
        });
    }

    int tail = rx_ring_tail_.load(std::memory_order_relaxed);
    if (tail == rx_ring_head_.load(std::memory_order_acquire)) {
        len = 0;
        return false;
    }

    RxSlot& slot = rx_ring_[tail];
    len = slot.bytes_received;
    std::copy(slot.data.begin(), slot.data.begin() + len, buf);
    rx_ring_tail_.store((tail + 1) % RX_RING_SIZE, std::memory_order_release);
    return true;
}

uint32_t DCA1000Socket::get_overrun_count() const {
    return rx_overrun_count_.load(std::memory_order_relaxed);
}

void DCA1000Socket::rx_thread_func() {
    while (rx_thread_running_.load(std::memory_order_relaxed)) {
        int cur_head = rx_ring_head_.load(std::memory_order_relaxed);
        int next_head = (cur_head + 1) % RX_RING_SIZE;

        if (next_head == rx_ring_tail_.load(std::memory_order_acquire)) {
            // Ring full: drain socket to prevent kernel buffer overflow
            rx_overrun_count_.fetch_add(1, std::memory_order_relaxed);
            uint8_t discard[1472];
            recvfrom(data_socket_, discard, sizeof(discard), 0, nullptr, nullptr);
            continue;
        }

        RxSlot& slot = rx_ring_[cur_head];
        ssize_t n = recvfrom(data_socket_, slot.data.data(), slot.data.size(), 0,
                             nullptr, nullptr);
        if (n <= 0) continue;
        slot.bytes_received = static_cast<int>(n);
        rx_ring_head_.store(next_head, std::memory_order_release);
        rx_ring_cv_.notify_one();
    }
}
