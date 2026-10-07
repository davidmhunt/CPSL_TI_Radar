#include "FirmwareIdentity.hpp"

#include <regex>
#include <sstream>

namespace cpsl {
namespace radar {

const char* to_string(FirmwareCheck c) {
    switch (c) {
        case FirmwareCheck::automatic: return "auto";
        case FirmwareCheck::warn: return "warn";
        case FirmwareCheck::off: return "off";
    }
    return "?";
}

const char* to_string(IdentityVerdict v) {
    switch (v) {
        case IdentityVerdict::match: return "match";
        case IdentityVerdict::mismatch: return "mismatch";
        case IdentityVerdict::unknown: return "unknown";
        case IdentityVerdict::skipped: return "skipped";
    }
    return "?";
}

namespace {

std::string clean(const std::string& s) {
    std::string r;
    r.reserve(s.size());
    for (char c : s) if (c != '\r') r += c;
    return r;
}

std::string trim(const std::string& t) {
    const char* ws = " \t\r\n\f\v";
    const size_t b = t.find_first_not_of(ws);
    if (b == std::string::npos) return std::string();
    return t.substr(b, t.find_last_not_of(ws) - b + 1);
}

bool search(const std::string& rx, const std::string& text, std::smatch* m = nullptr) {
    const std::regex re(rx, std::regex::ECMAScript);
    return m != nullptr ? std::regex_search(text, *m, re) : std::regex_search(text, re);
}

// First informative reply line (not the echoed command, not a prompt-only line, not "Done").
std::string first_line(const std::map<std::string, std::string>& replies, const std::vector<std::string>& cmds) {
    for (const std::string& c : cmds) {
        auto it = replies.find(c);
        if (it == replies.end()) continue;
        std::istringstream in(clean(it->second));
        std::string ln;
        while (std::getline(in, ln)) {
            const std::string s = trim(ln);
            if (s.empty() || s == c || s == "Done") continue;
            if (s.size() >= 3 && s.compare(s.size() - 3, 3, ":/>") == 0) continue;
            return s;
        }
    }
    return std::string();
}

}  // namespace

std::string strip_fixture(const std::string& text) {
    std::istringstream in(text);
    std::string ln, out;
    bool first = true;
    while (std::getline(in, ln)) {
        if (!ln.empty() && ln[0] == '#') continue;
        if (!first) out += "\n";
        out += ln;
        first = false;
    }
    return out;
}

IdentityResult match_firmware_identity(const FirmwareDescriptor::Identify* entry, bool once,
                                       const std::map<std::string, std::string>& replies) {
    IdentityResult out;
    if (entry == nullptr) {
        out.detail = "no identify data";
        return out;
    }
    out.level = entry->level;
    out.flash_hint = entry->flash_hint;
    for (const auto& p : entry->probes) out.probes.push_back(p.cmd);
    if (once && !entry->once_safe) {
        out.detail = "once-per-power-up board, not once_safe: not queried";
        return out;
    }
    std::vector<std::string> failed, missing;
    for (const auto& p : entry->probes) {
        auto it = replies.find(p.cmd);
        const std::string text = it == replies.end() ? std::string() : clean(it->second);
        if (trim(text).empty()) {
            missing.push_back(p.cmd);
            continue;
        }
        for (const auto& sh : p.show) {
            std::smatch m;
            if (search(sh.second, text, &m) && m.size() > 1) {
                const std::string v = trim(m[1].str());
                bool replaced = false;
                for (auto& f : out.fields) {
                    if (f.first == sh.first) { f.second = v; replaced = true; }
                }
                if (!replaced) out.fields.emplace_back(sh.first, v);
            }
        }
        for (const std::string& rx : p.require) {
            if (!search(rx, text)) failed.push_back(p.cmd + ": reply lacks /" + rx + "/");
        }
        for (const std::string& rx : p.reject) {
            if (search(rx, text)) failed.push_back(p.cmd + ": reply matches /" + rx + "/");
        }
    }
    for (const auto& f : out.fields) out.found += (out.found.empty() ? "" : " ") + f.first + "=" + f.second;
    if (out.found.empty()) out.found = first_line(replies, out.probes);
    if (out.found.empty()) out.found = "no reply";

    auto join = [](const std::vector<std::string>& v, const char* sep) {
        std::string r;
        for (const std::string& s : v) r += (r.empty() ? "" : sep) + s;
        return r;
    };
    if (entry->level == "unverified") {
        out.verdict = IdentityVerdict::unknown;
        out.detail = "identify entry is unverified: not enforced";
    } else if (!failed.empty()) {
        out.verdict = IdentityVerdict::mismatch;
        out.detail = join(failed, "; ");
    } else if (!missing.empty()) {
        out.verdict = IdentityVerdict::unknown;
        out.detail = "no reply to " + join(missing, ", ");
    } else {
        out.verdict = IdentityVerdict::match;
    }
    return out;
}

std::string firmware_mismatch_message(const std::string& fw, const std::string& board, const IdentityResult& r,
                                      const std::string& port) {
    return "firmware mismatch on " + port + ": system JSON expects " + fw + " (" + board + "), board answered " +
           r.found + ". Flash it: " + r.flash_hint + ", or set runtime.firmware_check \"warn\"";
}

std::string describe_firmware_check(const FirmwareDescriptor::Identify* entry, bool once, FirmwareCheck policy) {
    if (policy == FirmwareCheck::off) return "firmware check: off (runtime.firmware_check)";
    if (entry == nullptr) return "firmware check: none (the firmware descriptor has no identify data for this board)";
    std::string cmds;
    for (const auto& p : entry->probes) cmds += (cmds.empty() ? "" : ", ") + p.cmd;
    std::string s = "firmware check: " + cmds + " before the cfg (level " + entry->level;
    if (once && !entry->once_safe) s += "; skipped: once-per-power-up, not once_safe";
    else if (entry->level == "unverified") s += "; not enforced";
    if (policy == FirmwareCheck::warn) s += "; warn only";
    return s + ")";
}

}  // namespace radar
}  // namespace cpsl
