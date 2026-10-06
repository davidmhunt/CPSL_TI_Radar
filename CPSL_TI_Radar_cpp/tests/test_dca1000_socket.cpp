// DCA1000Socket over loopback (directive core-15): the RX thread and packet
// ring the DCA worker reads, with a test sender in place of the DCA1000.
// Nothing here sends a DCA1000 command; every socket is on 127.0.0.1.
//
//   P4  packets are read in place (views into the ring, no copy), in order,
//       in batches; a sleeping worker is woken by the RX thread.
//   P5  the RX thread takes a queued backlog with recvmmsg, in order, across
//       the end of the ring array; stop_rx() stays bounded by SO_RCVTIMEO.
#include "test_harness.hpp"
#include "DCA1000Socket.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <thread>
#include <vector>

#include "Log.hpp"

namespace {

using Clock = std::chrono::steady_clock;

// a free UDP port on 127.0.0.1 (bound to port 0, read back, closed)
int free_udp_port() {
    const int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    socklen_t n = sizeof(a);
    int port = -1;
    if (bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) == 0 &&
        getsockname(fd, reinterpret_cast<sockaddr*>(&a), &n) == 0)
        port = ntohs(a.sin_port);
    close(fd);
    return port;
}

// A DCA1000Socket bound on loopback plus a sender aimed at its data port.
struct Loopback {
    DCA1000Socket sock;
    int data_port = -1;
    int tx = -1;
    bool ok = false;

    explicit Loopback(size_t rcvbuf = 4 * 1024 * 1024) {
        const int cmd_port = free_udp_port();
        data_port = free_udp_port();
        if (cmd_port <= 0 || data_port <= 0 || cmd_port == data_port) return;
        if (!sock.init("127.0.0.1", "127.0.0.1", cmd_port, data_port, rcvbuf)) return;
        tx = socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in to{};
        to.sin_family = AF_INET;
        to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        to.sin_port = htons(static_cast<uint16_t>(data_port));
        ok = tx >= 0 && connect(tx, reinterpret_cast<sockaddr*>(&to), sizeof(to)) == 0;
    }
    ~Loopback() {
        sock.stop_rx();
        if (tx >= 0) close(tx);
    }
    // packet i: 4-byte index, then (len - 4) bytes of (i + k) & 0xff
    bool send_packet(uint32_t i, size_t len = 1472) {
        std::vector<uint8_t> p(len);
        std::memcpy(p.data(), &i, 4);
        for (size_t k = 4; k < len; k++) p[k] = static_cast<uint8_t>(i + k);
        return send(tx, p.data(), p.size(), 0) == static_cast<ssize_t>(p.size());
    }
};

bool packet_ok(const uint8_t* d, int len, uint32_t want, size_t want_len = 1472) {
    if (len != static_cast<int>(want_len)) return false;
    uint32_t i = 0;
    std::memcpy(&i, d, 4);
    if (i != want) return false;
    for (size_t k = 4; k < want_len; k++)
        if (d[k] != static_cast<uint8_t>(i + k)) return false;
    return true;
}

}  // namespace

TEST_CASE(packets_are_read_in_place_in_order_and_in_batches) {
    Loopback lb;
    CHECK(lb.ok);
    if (!lb.ok) return;
    lb.sock.start_rx();
    const uint32_t kPackets = 2000;
    std::thread sender([&] {
        for (uint32_t i = 0; i < kPackets; i++) {
            lb.send_packet(i);
            if (i % 64 == 63) std::this_thread::sleep_for(std::chrono::microseconds(200));
        }
    });
    uint32_t next = 0, bad = 0, batches = 0, largest = 0;
    DCA1000Socket::PacketView v[32];
    const Clock::time_point until = Clock::now() + std::chrono::seconds(10);
    while (next < kPackets && Clock::now() < until) {
        const int n = lb.sock.acquire_packets(v, 32, 200);
        for (int i = 0; i < n; i++) {
            if (!packet_ok(v[i].data, v[i].len, next)) bad++;
            next++;
        }
        if (n > 0) {
            batches++;
            largest = std::max<uint32_t>(largest, static_cast<uint32_t>(n));
        }
        lb.sock.release_packets(n);
    }
    sender.join();
    std::cout << "    " << next << " packets in " << batches << " batches (largest " << largest << ")" << std::endl;
    CHECK_EQ(next, kPackets);
    CHECK_EQ(bad, 0u);
    CHECK_EQ(lb.sock.get_overrun_count(), 0u);
}

TEST_CASE(views_point_into_the_ring_until_released) {
    Loopback lb;
    CHECK(lb.ok);
    if (!lb.ok) return;
    lb.sock.start_rx();
    CHECK(lb.send_packet(7, 100));
    CHECK(lb.send_packet(8, 200));
    DCA1000Socket::PacketView a{nullptr, 0}, b{nullptr, 0};
    CHECK_EQ(lb.sock.acquire_packets(&a, 1, 2000), 1);
    // not released: the same packet, at the same address (no copy)
    CHECK_EQ(lb.sock.acquire_packets(&b, 1, 2000), 1);
    CHECK(a.data == b.data);
    CHECK(packet_ok(a.data, a.len, 7, 100));
    lb.sock.release_packets(1);
    CHECK_EQ(lb.sock.acquire_packets(&b, 1, 2000), 1);
    CHECK(b.data != a.data);
    CHECK(packet_ok(b.data, b.len, 8, 200));
    lb.sock.release_packets(1);
    // pop_packet copies one out
    CHECK(lb.send_packet(9, 300));
    std::vector<uint8_t> buf(1472);
    int len = 0;
    CHECK(lb.sock.pop_packet(buf.data(), len, 2000));
    CHECK(packet_ok(buf.data(), len, 9, 300));
}

TEST_CASE(a_sleeping_worker_is_woken_by_the_rx_thread) {
    Loopback lb;
    CHECK(lb.ok);
    if (!lb.ok) return;
    lb.sock.start_rx();
    // nothing sent: acquire times out with 0
    DCA1000Socket::PacketView v{nullptr, 0};
    Clock::time_point t0 = Clock::now();
    CHECK_EQ(lb.sock.acquire_packets(&v, 1, 100), 0);
    const auto waited = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - t0).count();
    CHECK(waited >= 90 && waited < 2000);
    // a packet sent while the worker sleeps (5 s timeout) wakes it at once,
    // 20 times in a row (a lost wake-up would cost the full 5 s)
    long worst_ms = 0;
    for (uint32_t i = 0; i < 20; i++) {
        std::thread sender([&] {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            lb.send_packet(i);
        });
        t0 = Clock::now();
        const int n = lb.sock.acquire_packets(&v, 1, 5000);
        const long ms = static_cast<long>(
            std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - t0).count());
        sender.join();
        CHECK_EQ(n, 1);
        if (n == 1) CHECK(packet_ok(v.data, v.len, i));
        lb.sock.release_packets(n);
        worst_ms = std::max(worst_ms, ms);
    }
    std::cout << "    slowest wake-up " << worst_ms << " ms (packet sent 20 ms after the worker slept)" << std::endl;
    CHECK(worst_ms < 1000);
}

TEST_CASE(a_queued_backlog_is_taken_in_order) {
    Loopback lb;
    CHECK(lb.ok);
    if (!lb.ok) return;
    // 400 packets wait in the kernel buffer before the RX thread starts, so
    // its recvmmsg calls find full batches; 3 rounds wrap the 512-slot ring
    uint32_t next = 0, bad = 0;
    DCA1000Socket::PacketView v[32];
    for (int round = 0; round < 3; round++) {
        for (uint32_t i = 0; i < 400; i++) CHECK(lb.send_packet(round * 400 + i, 64 + (i % 7)));
        if (round == 0) lb.sock.start_rx();
        const uint32_t want = (round + 1) * 400;
        const Clock::time_point until = Clock::now() + std::chrono::seconds(10);
        while (next < want && Clock::now() < until) {
            const int n = lb.sock.acquire_packets(v, 32, 200);
            for (int i = 0; i < n; i++, next++)
                if (!packet_ok(v[i].data, v[i].len, next, 64 + ((next % 400) % 7))) bad++;
            lb.sock.release_packets(n);
        }
    }
    CHECK_EQ(next, 1200u);
    CHECK_EQ(bad, 0u);
    CHECK_EQ(lb.sock.get_overrun_count(), 0u);
    // the RX thread is blocked in recvmmsg with nothing to read: stop_rx()
    // returns within the 500 ms SO_RCVTIMEO
    const Clock::time_point t0 = Clock::now();
    lb.sock.stop_rx();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - t0).count();
    std::cout << "    stop_rx() took " << ms << " ms" << std::endl;
    CHECK(ms < 1500);
}

TEST_MAIN()
