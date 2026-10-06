#include "DCA1000Socket.hpp"
#include "Log.hpp"

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
      rx_thread_running_(false),
      worker_waiting_(false)
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
        cpsl::radar::log_error("DCA1000Socket: failed to create the cmd socket");
        return false;
    }

    data_socket_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (data_socket_ < 0) {
        cpsl::radar::log_error("DCA1000Socket: failed to create the data socket");
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
    granted_rcvbuf_ = actual_rcvbuf > 0 ? static_cast<size_t>(actual_rcvbuf) : 0;
    cpsl::radar::log_info("[DCA1000] SO_RCVBUF granted: ", actual_rcvbuf, " bytes");

    // Bind sockets
    if (bind(cmd_socket_, reinterpret_cast<struct sockaddr*>(&cmd_address_),
             sizeof(cmd_address_)) < 0) {
        cpsl::radar::log_error("DCA1000Socket: failed to bind the cmd socket to ", system_ip, ":", cmd_port);
        close(cmd_socket_); cmd_socket_ = -1;
        return false;
    }
    cpsl::radar::log_debug("Bound to command socket");

    if (bind(data_socket_, reinterpret_cast<struct sockaddr*>(&data_address_),
             sizeof(data_address_)) < 0) {
        cpsl::radar::log_error("DCA1000Socket: failed to bind the data socket to ", system_ip, ":", data_port);
        close(data_socket_); data_socket_ = -1;
        return false;
    }
    cpsl::radar::log_debug("Bound to data socket");

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
        cpsl::radar::log_warn("[DCA1000] could not set RX thread to SCHED_RR 99 ",
                              "(run as root or grant cap_sys_nice)");
    }
}

void DCA1000Socket::stop_rx() {
    rx_thread_running_.store(false, std::memory_order_relaxed);
    if (rx_thread_.joinable()) rx_thread_.join();
}

bool DCA1000Socket::send_command(std::vector<uint8_t>& cmd) {
    if (cmd_socket_ < 0) {
        cpsl::radar::log_error("DCA1000Socket: cmd socket not bound");
        return false;
    }
    ssize_t sent = sendto(cmd_socket_, cmd.data(), cmd.size(), 0,
                          reinterpret_cast<struct sockaddr*>(&fpga_address_),
                          sizeof(fpga_address_));
    if (sent != static_cast<ssize_t>(cmd.size())) {
        cpsl::radar::log_warn("DCA1000Socket: failed to send a command");
        return false;
    }
    return true;
}

bool DCA1000Socket::receive_response(std::vector<uint8_t>& buffer) {
    if (cmd_socket_ < 0) {
        cpsl::radar::log_error("DCA1000Socket: cmd socket not bound");
        return false;
    }
    struct sockaddr_in from{};
    socklen_t from_len = sizeof(from);
    ssize_t n = recvfrom(cmd_socket_, buffer.data(), buffer.size(), 0,
                         reinterpret_cast<struct sockaddr*>(&from), &from_len);
    if (n < 0) {
        cpsl::radar::log_warn("DCA1000Socket: no response from the DCA1000");
        return false;
    }
    return true;
}

int DCA1000Socket::acquire_packets(PacketView* out, int max, int timeout_ms) {
    const int tail = rx_ring_tail_.load(std::memory_order_relaxed);  // only this thread writes it
    int head = rx_ring_head_.load(std::memory_order_acquire);
    if (head == tail) {
        // about to sleep: say so first, then re-check under the mutex (the
        // RX thread notifies only when it sees worker_waiting_)
        std::unique_lock<std::mutex> lock(rx_ring_cv_mutex_);
        worker_waiting_.store(true, std::memory_order_seq_cst);
        rx_ring_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms), [this, tail] {
            return rx_ring_head_.load(std::memory_order_seq_cst) != tail;
        });
        worker_waiting_.store(false, std::memory_order_relaxed);
        head = rx_ring_head_.load(std::memory_order_acquire);
        if (head == tail) return 0;
    }
    const int available = (head - tail + RX_RING_SIZE) % RX_RING_SIZE;
    const int n = std::min(max, available);
    for (int i = 0; i < n; i++) {
        const RxSlot& slot = rx_ring_[(tail + i) % RX_RING_SIZE];
        out[i] = PacketView{slot.data.data(), slot.bytes_received};
    }
    return n;
}

void DCA1000Socket::release_packets(int n) {
    if (n <= 0) return;
    const int tail = rx_ring_tail_.load(std::memory_order_relaxed);
    rx_ring_tail_.store((tail + n) % RX_RING_SIZE, std::memory_order_release);
}

bool DCA1000Socket::pop_packet(uint8_t* buf, int& len, int timeout_ms) {
    PacketView v{nullptr, 0};
    if (acquire_packets(&v, 1, timeout_ms) == 0) {
        len = 0;
        return false;
    }
    len = v.len;
    std::copy(v.data, v.data + v.len, buf);
    release_packets(1);
    return true;
}

uint32_t DCA1000Socket::get_overrun_count() const {
    return rx_overrun_count_.load(std::memory_order_relaxed);
}

void DCA1000Socket::rx_thread_func() {
    // recvmmsg straight into the free ring slots (design P5): one syscall
    // takes up to kRecvBatch datagrams. MSG_WAITFORONE blocks (up to the
    // socket's SO_RCVTIMEO, 500 ms, so stop_rx() stays bounded) for the
    // first datagram only, then takes whatever else is already queued.
    std::array<mmsghdr, kRecvBatch> msgs{};
    std::array<iovec, kRecvBatch> iov{};
    while (rx_thread_running_.load(std::memory_order_relaxed)) {
        const int head = rx_ring_head_.load(std::memory_order_relaxed);
        const int tail = rx_ring_tail_.load(std::memory_order_acquire);
        const int free_slots = (tail - head - 1 + RX_RING_SIZE) % RX_RING_SIZE;

        if (free_slots == 0) {
            // Ring full: drain socket to prevent kernel buffer overflow
            rx_overrun_count_.fetch_add(1, std::memory_order_relaxed);
            uint8_t discard[1472];
            recvfrom(data_socket_, discard, sizeof(discard), 0, nullptr, nullptr);
            continue;
        }

        // free slots from head up to the end of the array (no wrap in one call)
        const int n = std::min({free_slots, RX_RING_SIZE - head, kRecvBatch});
        for (int i = 0; i < n; i++) {
            RxSlot& slot = rx_ring_[head + i];
            iov[i].iov_base = slot.data.data();
            iov[i].iov_len = slot.data.size();
            msgs[i].msg_hdr = msghdr{};
            msgs[i].msg_hdr.msg_iov = &iov[i];
            msgs[i].msg_hdr.msg_iovlen = 1;
            msgs[i].msg_len = 0;
        }
        const int got = recvmmsg(data_socket_, msgs.data(), static_cast<unsigned>(n), MSG_WAITFORONE, nullptr);
        if (got <= 0) continue;  // timeout (stop check) or EINTR
        for (int i = 0; i < got; i++) {
            rx_ring_[head + i].bytes_received = static_cast<int>(msgs[i].msg_len);
        }
        rx_ring_head_.store((head + got) % RX_RING_SIZE, std::memory_order_seq_cst);
        // wake the worker only if it is (about to be) asleep; taking the
        // mutex first means it is either still before its re-check (and will
        // see the new head) or already waiting (and gets the notify)
        if (worker_waiting_.load(std::memory_order_seq_cst)) {
            { std::lock_guard<std::mutex> lock(rx_ring_cv_mutex_); }
            rx_ring_cv_.notify_one();
        }
    }
}
