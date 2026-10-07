#include "SerialStreamer.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#include <system_error>

#include "Log.hpp"

using cpsl::radar::ByteStream;
using cpsl::radar::Status;
using cpsl::radar::UartFrame;

namespace {
//longest single wait inside process_next_message, so close() ends it promptly
constexpr std::chrono::milliseconds kReadSlice(100);
}  // namespace

bool SerialStreamer::initialize(const SystemConfigReader & systemConfigReader){
    stream_.reset();  //closes a port this streamer opened before
    initialized = false;
    raw_out_.close();
    if(!systemConfigReader.initialized){
        cpsl::radar::log_error("attempted to initialize the serial streamer, ",
                               "but system_config_reader was not initialized");
        return false;
    }
    std::string error;
    std::shared_ptr<cpsl::radar::SerialPortStream> port = cpsl::radar::SerialPortStream::open(
        systemConfigReader.getRadarDataPort(), systemConfigReader.getRadarDataBaudRate(), error);
    if(!port){
        cpsl::radar::log_error("SerialStreamer: ", error);
        return false;
    }
    return initialize(systemConfigReader, port);
}

bool SerialStreamer::initialize(const SystemConfigReader & systemConfigReader,
                                std::shared_ptr<ByteStream> stream){
    system_config_reader = systemConfigReader;
    stream_ = std::move(stream);
    initialized = system_config_reader.initialized && stream_ != nullptr;

    dialect_ = system_config_reader.getBoard().data_uart.tlv_dialect;
    header_bytes_ = cpsl::radar::uart_header_bytes(dialect_);
    timeout_ms_ = system_config_reader.getRadarDataTimeoutMs();
    rx_len_ = 0;
    synced_ = false;
    warned_compact_ = false;
    {
        std::lock_guard<std::mutex> l(m_);
        published_points_.clear();
        published_frame_number_ = 0;
        committed_frames_ = 0;
        taken_at_ = 0;
        have_previous_frame_ = false;
        previous_frame_number_ = 0;
        missed_frame_count_ = 0;
    }
    raw_failed_ = false;
    if(initialized && system_config_reader.get_save_serial_bytes()){
        //64 kB buffer: the file is written in large blocks, not per read
        raw_buf_.resize(64 * 1024);
        raw_out_.clear();
        raw_out_.rdbuf()->pubsetbuf(raw_buf_.data(), static_cast<std::streamsize>(raw_buf_.size()));
        const std::string path = system_config_reader.get_output_path("serial_data.bin");
        raw_out_.open(path, std::ios::out | std::ios::binary | std::ios::trunc);
        if(!raw_out_.is_open()){
            cpsl::radar::log_error("Failed to open or create ", path);
            initialized = false;
        }
    }
    closed_.store(false);
    last_frame_ns_.store(0, std::memory_order_relaxed);
    io_error_.store(false, std::memory_order_relaxed);
    rejected_frames_.store(0, std::memory_order_relaxed);
    return initialized;
}

bool SerialStreamer::process_next_message(void){
    const bool ok = process_next_message_impl();
    if(raw_out_.is_open() && !raw_failed_){
        raw_out_.flush();
        if(!raw_out_){
            raw_failed_ = true;
            cpsl::radar::log_warn("SerialStreamer: writing serial_data.bin failed; the raw bytes are no longer ",
                                  "saved (the stream continues)");
        }
    }
    return ok;
}

void SerialStreamer::write_raw(const uint8_t * data, size_t n){
    if(raw_failed_ || !raw_out_.is_open() || n == 0) return;
    raw_out_.write(reinterpret_cast<const char *>(data), static_cast<std::streamsize>(n));
    if(!raw_out_){
        raw_failed_ = true;
        cpsl::radar::log_warn("SerialStreamer: writing serial_data.bin failed; the raw bytes are no longer ",
                              "saved (the stream continues)");
    }
}

bool SerialStreamer::process_next_message_impl(void){

    if(!stream_){
        return false;
    }
    const clock::time_point deadline = clock::now() + std::chrono::milliseconds(timeout_ms_);

    for(;;){
        if(closed_.load(std::memory_order_relaxed)){
            return false;
        }

        //1. a magic word at rx_[0]; keep a possible partial one at the end
        const size_t magic = cpsl::radar::find_uart_magic(rx_.data(), rx_len_);
        if(magic == rx_len_){
            discard(rx_len_ > 7 ? rx_len_ - 7 : 0);
            if(!read_more(header_bytes_, deadline)) return false;
            continue;
        }
        if(magic > 0){
            if(synced_){
                cpsl::radar::log_debug("SerialStreamer: skipped ", magic, " bytes before a magic word");
            }
            discard(magic);
        }

        //2. the header, for totalPacketLen
        if(rx_len_ < header_bytes_){
            if(!read_more(header_bytes_ - rx_len_, deadline)) return false;
            continue;
        }
        const uint32_t total = cpsl::radar::uart_le32(rx_.data(), 12);
        if(total < header_bytes_ || total > cpsl::radar::kUartMaxPacketBytes){
            rejected_frames_.fetch_add(1, std::memory_order_relaxed);
            cpsl::radar::log_warn("SerialStreamer: dropped a frame with totalPacketLen ", total,
                                  " (resynchronizing)");
            discard(1);
            continue;
        }

        //3. exactly the rest of the frame, then parse and publish at once
        if(rx_len_ < total){
            if(!read_more(total - rx_len_, deadline)) return false;
            continue;
        }
        const clock::time_point completed_at = clock::now();
        const Status s = cpsl::radar::parse_uart_frame(rx_.data(), total, dialect_, work_);
        if(!s){
            rejected_frames_.fetch_add(1, std::memory_order_relaxed);
            cpsl::radar::log_warn("SerialStreamer: dropped a frame: ", s.message);
            discard(1);  //search again from just past this magic word
            continue;
        }
        if(work_.compact_points_skipped && !warned_compact_){
            warned_compact_ = true;
            cpsl::radar::log_warn("SerialStreamer: the cascade demo sends compact points (TLV 12, guiMonitor ",
                                  "detectedObjects 3), which the driver does not decode: point clouds stay ",
                                  "empty. Set detectedObjects to 1 (points + SNR/noise) or 2 in the radar cfg.");
        }
        if(cpsl::radar::log_enabled(cpsl::radar::LogLevel::debug)){
            const cpsl::radar::UartHeader & h = work_.header;
            //the platform word tells which demo is sending (a tlv_dialect check)
            char platform[16];
            std::snprintf(platform, sizeof platform, "0x%X", h.platform);
            cpsl::radar::log_debug("SerialStreamer: frame ", h.frame_number, ", platform ", platform, ", ",
                                   total, " bytes, ", h.num_tlvs, " TLVs, ", work_.points.size(), " points");
        }
        discard(total);
        commit(completed_at);
        synced_ = true;
        return true;
    }
}

bool SerialStreamer::read_more(size_t want, clock::time_point deadline){
    const clock::time_point now = clock::now();
    if(now >= deadline){
        cpsl::radar::log_debug("SerialStreamer: no complete frame within ", timeout_ms_, " ms");
        return false;
    }
    if(rx_.size() < rx_len_ + want){
        rx_.resize(rx_len_ + want);
    }
    const std::chrono::milliseconds left =
        std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now) + std::chrono::milliseconds(1);
    size_t n = 0;
    const std::error_code ec = stream_->read_some(rx_.data() + rx_len_, want, n, std::min(left, kReadSlice));
    if(ec && ec != std::errc::timed_out){
        io_error_.store(true, std::memory_order_relaxed);
        cpsl::radar::log_error("SerialStreamer: error while reading the data port: ", ec.message());
        return false;
    }
    io_error_.store(false, std::memory_order_relaxed);
    write_raw(rx_.data() + rx_len_, std::min(n, want));
    rx_len_ += std::min(n, want);
    return true;
}

void SerialStreamer::discard(size_t n){
    n = std::min(n, rx_len_);
    if(n == 0) return;
    if(n < rx_len_){
        std::memmove(rx_.data(), rx_.data() + n, rx_len_ - n);
    }
    rx_len_ -= n;
}

void SerialStreamer::commit(clock::time_point completed_at){
    {
        std::lock_guard<std::mutex> l(m_);
        published_points_.swap(work_.points);
        published_frame_number_ = work_.header.frame_number;
        published_at_ = completed_at;

        //track gaps in the frame number (dropped/corrupted frames)
        const uint32_t fn = work_.header.frame_number;
        if(have_previous_frame_ && fn != previous_frame_number_ + 1){
            const uint32_t missed = fn - previous_frame_number_ - 1;
            missed_frame_count_ += missed;
            cpsl::radar::log_warn("SerialStreamer: frame number jumped from ", previous_frame_number_,
                                  " to ", fn, " (", missed_frame_count_, " missed in total)");
        }
        have_previous_frame_ = true;
        previous_frame_number_ = fn;
        committed_frames_ += 1;
    }
    last_frame_ns_.store(std::chrono::duration_cast<std::chrono::nanoseconds>(
                             completed_at.time_since_epoch()).count(),
                         std::memory_order_relaxed);
    cv_.notify_all();
}

bool SerialStreamer::take_frame(std::vector<cpsl::radar::Point> & points,
                                uint32_t & frame_number,
                                clock::time_point & completed_at,
                                uint64_t & overwritten,
                                clock::time_point wait_until){
    std::unique_lock<std::mutex> l(m_);
    cv_.wait_until(l, wait_until, [this]{
        return committed_frames_ != taken_at_ || closed_.load(std::memory_order_relaxed);
    });
    if(committed_frames_ == taken_at_){
        return false;
    }
    overwritten = committed_frames_ - taken_at_ - 1;
    taken_at_ = committed_frames_;
    points.swap(published_points_);
    frame_number = published_frame_number_;
    completed_at = published_at_;
    return true;
}

void SerialStreamer::close(void){
    {
        std::lock_guard<std::mutex> l(m_);
        closed_.store(true);
    }
    cv_.notify_all();
}

uint32_t SerialStreamer::get_latest_frame_number(void){
    std::lock_guard<std::mutex> l(m_);
    return published_frame_number_;
}

uint32_t SerialStreamer::get_missed_frame_count(void){
    std::lock_guard<std::mutex> l(m_);
    return missed_frame_count_;
}

uint64_t SerialStreamer::get_committed_frame_count(void){
    std::lock_guard<std::mutex> l(m_);
    return committed_frames_;
}
