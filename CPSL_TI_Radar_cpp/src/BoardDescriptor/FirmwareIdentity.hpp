#ifndef CPSL_RADAR_FIRMWARE_IDENTITY_HPP
#define CPSL_RADAR_FIRMWARE_IDENTITY_HPP

// Firmware identity matcher (directive gui-33): pure, no I/O. Given what the
// board answered to a firmware's identify probes (FirmwareDescriptor::identify)
// say whether it runs that firmware. Mirrors radar_gui/fwident.py; parity is
// pinned by tests/data/fw_replies/manifest.json (test_firmware_identity.cpp
// and tests/test_radar_gui_fwident.py).
//
//   skipped  no identify data, or a once-per-power-up board whose entry is not
//            once_safe: the board is never queried
//   unknown  level "unverified", or no / partial reply with no failing probe
//            (warn and continue)
//   mismatch a probe's reply fails `require` or hits `reject` (fatal under
//            runtime.firmware_check "auto")
//   match    every probe answered and passed

#include <map>
#include <string>
#include <utility>
#include <vector>

#include "FirmwareDescriptor.hpp"

namespace cpsl {
namespace radar {

// runtime.firmware_check
enum class FirmwareCheck { automatic, warn, off };
const char* to_string(FirmwareCheck c);

enum class IdentityVerdict { match, mismatch, unknown, skipped };
const char* to_string(IdentityVerdict v);

struct IdentityResult {
    IdentityVerdict verdict = IdentityVerdict::skipped;
    std::vector<std::pair<std::string, std::string>> fields;  // shown fields, in display order
    std::string found;       // "platform=xWR18xx sdk=03.06.02.00 ..." or the first reply line, or "no reply"
    std::string detail;      // why (failed patterns, missing replies); "" for a match
    std::string flash_hint;
    std::string level;       // "" when there was no entry
    std::vector<std::string> probes;  // probe commands of the entry
};

// `entry` null = no identify data for the board. `once` = the board accepts a cfg once per power-up.
// `replies` maps a probe cmd to the board's reply text; missing or blank = no reply.
IdentityResult match_firmware_identity(const FirmwareDescriptor::Identify* entry, bool once,
                                       const std::map<std::string, std::string>& replies);

// "firmware mismatch on <port>: system JSON expects <fw> (<board>), board answered <found>. Flash it: <hint>"
std::string firmware_mismatch_message(const std::string& fw, const std::string& board, const IdentityResult& r,
                                      const std::string& port);

// The --validate note: what would be sent before the cfg (sends nothing).
std::string describe_firmware_check(const FirmwareDescriptor::Identify* entry, bool once, FirmwareCheck policy);

// A fixture file's reply text: drops the '# ...' provenance header lines.
std::string strip_fixture(const std::string& text);

}  // namespace radar
}  // namespace cpsl

#endif
