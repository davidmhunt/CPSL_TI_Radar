#include "PacketSource.hpp"

#include <algorithm>
#include <cstring>

#include "DCA1000Commands.hpp"
#include "Log.hpp"

namespace cpsl {
namespace radar {

size_t PacketSource::acquire(PacketView* out, size_t max, std::chrono::milliseconds timeout) {
    int len = 0;
    if (max == 0 || !pop(one_, len, timeout)) return 0;
    out[0] = PacketView{one_, len};
    return 1;
}

void PacketSource::release(size_t) {}

// ---------------------------------------------------------------------------
// UdpPacketSource
// ---------------------------------------------------------------------------

UdpPacketSource::UdpPacketSource(const SystemConfigReader& config) : config_(config) {}

Status UdpPacketSource::open() {
    if (!socket_.init(config_.getDCAFpgaIP(), config_.getDCASystemIP(), config_.getDCACmdPort(),
                      config_.getDCADataPort(), config_.getDCARcvbufBytes())) {
        return Status(Code::open_failed, "cannot open the DCA1000 sockets on " + config_.getDCASystemIP() +
                                             " (cmd port " + std::to_string(config_.getDCACmdPort()) +
                                             ", data port " + std::to_string(config_.getDCADataPort()) + ")");
    }
    log_debug("FPGA IP: ", config_.getDCAFpgaIP(), ", system IP: ", config_.getDCASystemIP(),
              ", cmd port: ", config_.getDCACmdPort(), ", data port: ", config_.getDCADataPort());
    return Status::ok();
}

Status UdpPacketSource::configure() {
    if (!socket_.is_initialized()) {
        return Status(Code::invalid_state, "DCA1000 sockets are not open");
    }
    const BoardDescriptor& board = config_.getBoard();
    const std::string at = " (DCA1000 at " + config_.getDCAFpgaIP() + ")";
    if (!send_systemConnect()) return Status(Code::device_error, "DCA1000 did not answer SYSTEM_CONNECT" + at);
    if (!send_resetFPGA()) return Status(Code::device_error, "DCA1000 did not acknowledge RESET_FPGA" + at);
    // dca1000.packet_bytes / packet_delay_us (1472 B / 100 us on every shipped board)
    if (!send_configPacketData(board.dca1000.packet_bytes, static_cast<uint16_t>(board.dca1000.packet_delay_us))) {
        return Status(Code::device_error, "DCA1000 did not acknowledge CONFIG_PACKET_DATA" + at);
    }
    if (!send_configFPGAGen()) return Status(Code::device_error, "DCA1000 did not acknowledge CONFIG_FPGA_GEN" + at);
    const float version = send_readFPGAVersion();
    if (version <= 0) return Status(Code::device_error, "DCA1000 did not report its FPGA version" + at);
    log_info("FPGA (firmware version: ", version, ") initialized successfully");
    return Status::ok();
}

Status UdpPacketSource::start() {
    if (started_) return Status::ok();
    if (!send_recordStart()) {
        return Status(Code::device_error, "DCA1000 did not acknowledge RECORD_START");
    }
    started_ = true;
    return Status::ok();
}

Status UdpPacketSource::stop() {
    // joins the RX thread even if recordStart never succeeded
    if (!started_) {
        socket_.stop_rx();
        return Status::ok();
    }
    started_ = false;
    if (!send_recordStop()) {
        return Status(Code::device_error, "DCA1000 did not acknowledge RECORD_STOP");
    }
    return Status::ok();
}

bool UdpPacketSource::pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) {
    return socket_.pop_packet(buf, len, static_cast<int>(timeout.count()));
}

size_t UdpPacketSource::acquire(PacketView* out, size_t max, std::chrono::milliseconds timeout) {
    return static_cast<size_t>(
        socket_.acquire_packets(out, static_cast<int>(max), static_cast<int>(timeout.count())));
}

void UdpPacketSource::release(size_t n) { socket_.release_packets(static_cast<int>(n)); }

bool UdpPacketSource::command(std::vector<uint8_t> cmd, uint16_t* status_out) {
    if (!socket_.send_command(cmd)) return false;
    std::vector<uint8_t> rcv_data(8, 0);
    if (!socket_.receive_response(rcv_data)) return false;
    const uint16_t status = static_cast<uint16_t>(static_cast<uint16_t>(rcv_data[5]) << 8 | rcv_data[4]);
    if (status_out != nullptr) *status_out = status;
    return status == 0;
}

bool UdpPacketSource::send_systemConnect() {
    return command(DCA1000Commands::construct_command(DCA1000Commands::SYSTEM_CONNECT));
}

bool UdpPacketSource::send_resetFPGA() {
    return command(DCA1000Commands::construct_command(DCA1000Commands::RESET_FPGA));
}

bool UdpPacketSource::send_configPacketData(size_t packet_size, uint16_t delay_us) {
    std::vector<uint8_t> data(6, 0);
    const uint16_t pkt_size = static_cast<uint16_t>(packet_size);
    data[0] = static_cast<uint8_t>(pkt_size & 0xFF);
    data[1] = static_cast<uint8_t>((pkt_size >> 8) & 0xFF);
    data[2] = static_cast<uint8_t>(delay_us & 0xFF);
    data[3] = static_cast<uint8_t>((delay_us >> 8) & 0xFF);
    // bytes 4 and 5 are reserved
    return command(DCA1000Commands::construct_command(DCA1000Commands::CONFIG_PACKET_DATA, data));
}

bool UdpPacketSource::send_configFPGAGen() {
    const BoardDescriptor& board = config_.getBoard();
    if (!board.lvds.supported) {
        log_error("UdpPacketSource::send_configFPGAGen(): board ", board.name,
                  " has no LVDS capture support (lvds.supported false)");
        return false;
    }
    std::vector<uint8_t> data(6, 0);
    data[0] = 0x01;                                // data logging mode: raw
    data[1] = board.lvds.lanes == 4 ? 0x01 : 0x02;  // LVDS mode: 0x01 = 4-lane, 0x02 = 2-lane
    data[2] = 0x01;                                // data transfer mode: LVDS capture
    data[3] = 0x02;                                // data capture mode: ethernet stream
    data[4] = 0x03;                                // data format mode: 16 bit
    data[5] = static_cast<uint8_t>(board.dca1000.fpga_timer_s);  // timer (30 s on every shipped board)
    return command(DCA1000Commands::construct_command(DCA1000Commands::CONFIG_FPGA_GEN, data));
}

float UdpPacketSource::send_readFPGAVersion() {
    uint16_t status = 0;
    // the "status" field carries the version here, so a non-zero value is no failure
    command(DCA1000Commands::construct_command(DCA1000Commands::READ_FPGA_VERSION), &status);
    if (status == 0) return 0.0f;
    const uint16_t major_version = status & 0b01111111;
    const uint16_t minor_version = (status >> 7) & 0b01111111;
    return static_cast<float>(major_version) + static_cast<float>(minor_version) * 1e-1f;
}

bool UdpPacketSource::send_recordStart() {
    if (!command(DCA1000Commands::construct_command(DCA1000Commands::RECORD_START))) return false;
    socket_.start_rx({config_.get_rx_cpu(), config_.get_rx_priority()});
    return true;
}

bool UdpPacketSource::send_recordStop() {
    // stop the RX thread before telling the DCA1000 to stop
    socket_.stop_rx();
    return command(DCA1000Commands::construct_command(DCA1000Commands::RECORD_STOP));
}

// ---------------------------------------------------------------------------
// ReplayPacketSource
// ---------------------------------------------------------------------------

ReplayPacketSource::ReplayPacketSource(std::vector<std::vector<uint8_t>> packets) {
    for (auto& p : packets) queue_.push_back(std::move(p));
}

void ReplayPacketSource::push(std::vector<uint8_t> packet) {
    {
        std::lock_guard<std::mutex> l(m_);
        queue_.push_back(std::move(packet));
    }
    cv_.notify_all();
}

Status ReplayPacketSource::start() {
    {
        std::lock_guard<std::mutex> l(m_);
        started_ = true;
    }
    cv_.notify_all();
    return Status::ok();
}

Status ReplayPacketSource::stop() {
    {
        std::lock_guard<std::mutex> l(m_);
        started_ = false;
    }
    cv_.notify_all();
    return Status::ok();
}

bool ReplayPacketSource::pop(uint8_t* buf, int& len, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> l(m_);
    len = 0;
    if (!cv_.wait_for(l, timeout, [this] { return started_ && !queue_.empty(); })) return false;
    std::vector<uint8_t>& p = queue_.front();
    const size_t n = std::min(p.size(), kMaxPacketBytes);
    std::memcpy(buf, p.data(), n);
    len = static_cast<int>(n);
    queue_.pop_front();
    return true;
}

size_t ReplayPacketSource::remaining() const {
    std::lock_guard<std::mutex> l(m_);
    return queue_.size();
}

bool ReplayPacketSource::started() const {
    std::lock_guard<std::mutex> l(m_);
    return started_;
}

}  // namespace radar
}  // namespace cpsl
