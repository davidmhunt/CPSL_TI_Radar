// DCA1000Commands: byte-exact command packets.
//
// Reference: TI DCA1000EVM CLI Software Developer Guide
// (DCA_Programming/Docs/TI_DCA1000EVM_CLI_Software_DeveloperGuide.pdf).
// Every command is  header 0xA55A | command code | data size | data | footer 0xEEAA,
// all UINT16 little-endian, so on the wire: 5A A5 <cc> 00 <len> 00 <data> AA EE.
#include "test_harness.hpp"
#include "DCA1000Commands.hpp"

typedef std::vector<uint8_t> Bytes;

static Bytes expect_no_data(uint8_t code) {
    return Bytes{0x5A, 0xA5, code, 0x00, 0x00, 0x00, 0xAA, 0xEE};
}

TEST_CASE(command_codes_match_cli_guide) {
    CHECK_EQ(DCA1000Commands::RESET_FPGA, 0x01);
    CHECK_EQ(DCA1000Commands::RESET_AR_DEV, 0x02);
    CHECK_EQ(DCA1000Commands::CONFIG_FPGA_GEN, 0x03);
    CHECK_EQ(DCA1000Commands::CONFIG_EEPROM, 0x04);
    CHECK_EQ(DCA1000Commands::RECORD_START, 0x05);
    CHECK_EQ(DCA1000Commands::RECORD_STOP, 0x06);
    CHECK_EQ(DCA1000Commands::PLAYBACK_START, 0x07);
    CHECK_EQ(DCA1000Commands::PLAYBACK_STOP, 0x08);
    CHECK_EQ(DCA1000Commands::SYSTEM_CONNECT, 0x09);
    CHECK_EQ(DCA1000Commands::SYSTEM_ERROR, 0x0A);
    CHECK_EQ(DCA1000Commands::CONFIG_PACKET_DATA, 0x0B);
    CHECK_EQ(DCA1000Commands::CONFIG_DATA_MODE_AR_DEV, 0x0C);
    CHECK_EQ(DCA1000Commands::INIT_FPGA_PLAYBACK, 0x0D);
    CHECK_EQ(DCA1000Commands::READ_FPGA_VERSION, 0x0E);
}

TEST_CASE(commands_without_data) {
    const uint16_t codes[] = {
        DCA1000Commands::RESET_FPGA,     DCA1000Commands::RESET_AR_DEV,
        DCA1000Commands::CONFIG_FPGA_GEN, DCA1000Commands::CONFIG_EEPROM,
        DCA1000Commands::RECORD_START,   DCA1000Commands::RECORD_STOP,
        DCA1000Commands::PLAYBACK_START, DCA1000Commands::PLAYBACK_STOP,
        DCA1000Commands::SYSTEM_CONNECT, DCA1000Commands::SYSTEM_ERROR,
        DCA1000Commands::CONFIG_PACKET_DATA, DCA1000Commands::CONFIG_DATA_MODE_AR_DEV,
        DCA1000Commands::INIT_FPGA_PLAYBACK, DCA1000Commands::READ_FPGA_VERSION};
    for (uint16_t c : codes) {
        CHECK(DCA1000Commands::construct_command(c) == expect_no_data(static_cast<uint8_t>(c)));
    }
}

TEST_CASE(named_commands_used_by_handler) {
    // Well-known TI byte sequences (also used by the TI CLI tool).
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::SYSTEM_CONNECT) ==
          (Bytes{0x5A, 0xA5, 0x09, 0x00, 0x00, 0x00, 0xAA, 0xEE}));
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::RESET_FPGA) ==
          (Bytes{0x5A, 0xA5, 0x01, 0x00, 0x00, 0x00, 0xAA, 0xEE}));
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::RECORD_START) ==
          (Bytes{0x5A, 0xA5, 0x05, 0x00, 0x00, 0x00, 0xAA, 0xEE}));
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::RECORD_STOP) ==
          (Bytes{0x5A, 0xA5, 0x06, 0x00, 0x00, 0x00, 0xAA, 0xEE}));
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::READ_FPGA_VERSION) ==
          (Bytes{0x5A, 0xA5, 0x0E, 0x00, 0x00, 0x00, 0xAA, 0xEE}));
}

TEST_CASE(explicit_empty_data_equals_default) {
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::RECORD_START, Bytes()) ==
          DCA1000Commands::construct_command(DCA1000Commands::RECORD_START));
}

TEST_CASE(config_fpga_gen_payload) {
    // Guide Table 6 defaults for Ethernet streaming: raw mode (1), 2-lane (2),
    // LVDS capture (1), Ethernet stream (2), 16-bit (3), timer 30 s.
    // (Payload layout as built by DCA1000Handler::send_configFPGAGen for 1843/6843.)
    Bytes data{0x01, 0x02, 0x01, 0x02, 0x03, 30};
    Bytes expected{0x5A, 0xA5, 0x03, 0x00, 0x06, 0x00,
                   0x01, 0x02, 0x01, 0x02, 0x03, 0x1E,
                   0xAA, 0xEE};
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::CONFIG_FPGA_GEN, data) == expected);
}

TEST_CASE(config_packet_data_payload) {
    // Guide: packet size 1472 (0x05C0), inter-packet delay 25 us, 2 future-use bytes.
    Bytes data{0xC0, 0x05, 0x19, 0x00, 0x00, 0x00};
    Bytes expected{0x5A, 0xA5, 0x0B, 0x00, 0x06, 0x00,
                   0xC0, 0x05, 0x19, 0x00, 0x00, 0x00,
                   0xAA, 0xEE};
    CHECK(DCA1000Commands::construct_command(DCA1000Commands::CONFIG_PACKET_DATA, data) == expected);
}

TEST_CASE(length_field_is_little_endian_16_bit) {
    Bytes data(300, 0x7F);  // 300 = 0x012C
    Bytes cmd = DCA1000Commands::construct_command(DCA1000Commands::CONFIG_PACKET_DATA, data);
    CHECK_EQ(cmd.size(), static_cast<size_t>(8 + 300));
    CHECK_EQ(cmd[4], 0x2C);
    CHECK_EQ(cmd[5], 0x01);
    CHECK_EQ(cmd[6], 0x7F);
    CHECK_EQ(cmd[6 + 299], 0x7F);
    CHECK_EQ(cmd[cmd.size() - 2], 0xAA);
    CHECK_EQ(cmd[cmd.size() - 1], 0xEE);
}

TEST_CASE(command_code_high_byte_is_encoded) {
    // Codes above 0xFF are not used today, but the encoder writes both bytes.
    Bytes cmd = DCA1000Commands::construct_command(0x1234);
    CHECK_EQ(cmd[2], 0x34);
    CHECK_EQ(cmd[3], 0x12);
}

TEST_MAIN()
