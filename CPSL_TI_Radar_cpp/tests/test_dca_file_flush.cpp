// adc_data.bin is exact after stop() (directive core-11 Step 5).
//
// RESULTS.md Finding 1: a SIGINT stop left adc_data.bin 896 B short on every
// DCA baseline run (303408000 B expected, 303407104 written = the largest
// multiple of the 8192 B ofstream buffer), while a stop that ran the
// destructors was exact: the old handler called exit(0) without closing the
// file. The handler now only sets a flag and the driver calls stop(), which
// flushes and closes the file. Here N frames go through the DCA file writer
// (configure_pipeline + ingest_packet, no socket) and stop() is called
// without destroying the handler.
#include "test_harness.hpp"
#include "dca_test_support.hpp"
#include "DCA1000Handler.hpp"

#include <sys/stat.h>

static long long file_size(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0 ? static_cast<long long>(st.st_size) : -1;
}

TEST_CASE(adc_data_bin_is_exact_after_stop) {
    const std::string out = dca_test::tmp_dir() + "/flush_out";
    mkdir(out.c_str(), 0755);
    SystemConfigReader sys(dca_test::write_system_config("flush", out, true));
    CHECK(sys.initialized);
    const cpsl::radar::BoardDescriptor& b = sys.getBoard();
    RadarConfigReader radar(sys.getRadarConfigPath(), b.cfg_dialect.rx_mask_fields, b.cfg_dialect.frame_period_field);
    const size_t B = radar.get_bytes_per_frame();

    DCA1000Handler h;
    CHECK(h.configure_pipeline(sys, radar));
    const std::string bin = out + "/adc_data.bin";
    CHECK_EQ(file_size(bin), 0LL);

    const int N = 5;
    uint32_t seq = 1;
    for (int k = 0; k < N; k++)
        for (const auto& p : dca_test::frame_packets(static_cast<uint64_t>(k), B, static_cast<uint16_t>(k + 1), seq))
            h.ingest_packet(p.data(), static_cast<int>(p.size()));
    const long long expected = static_cast<long long>(N) * static_cast<long long>(B);

    // the bug's mechanism: until the file is closed, the ofstream buffer
    // holds the tail (5 x 231840 B = 1159200 B, 4128 B past a 8192 B boundary)
    const long long before = file_size(bin);
    std::cout << "    before stop(): " << before << " of " << expected << " B on disk" << std::endl;
    CHECK(before < expected);

    CHECK(h.stop());
    CHECK_EQ(file_size(bin), expected);
    CHECK(h.stop());  // idempotent
    CHECK_EQ(file_size(bin), expected);

    // the first sample on disk is frame 1's tag (chirp 0, rx 0, sample 0: I then Q)
    std::ifstream f(bin, std::ios::binary);
    int16_t iq[2] = {0, 0};
    f.read(reinterpret_cast<char*>(iq), sizeof iq);
    CHECK_EQ(iq[0], 1);
    CHECK_EQ(iq[1], 1);
}

TEST_CASE(stop_without_output_files_is_harmless) {
    SystemConfigReader sys(dca_test::write_system_config("flush_nofile", dca_test::tmp_dir(), false));
    const cpsl::radar::BoardDescriptor& b = sys.getBoard();
    RadarConfigReader radar(sys.getRadarConfigPath(), b.cfg_dialect.rx_mask_fields, b.cfg_dialect.frame_period_field);
    DCA1000Handler h;
    CHECK(h.configure_pipeline(sys, radar));
    CHECK(h.stop());
    DCA1000Handler never_configured;
    CHECK(never_configured.stop());
}

TEST_MAIN()
