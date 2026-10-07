#include "FirmwareDescriptor.hpp"

#include <fstream>

#include "BoardDescriptor.hpp"  // parse_json_strict

using nlohmann::json;

namespace cpsl {
namespace radar {

const std::set<std::string>& FirmwareDescriptor::gui_only_keys() {
    static const std::set<std::string> keys = {"lvds_data_fmts", "mimo", "identify", "pending"};
    return keys;
}

std::string FirmwareDescriptor::gui_board_for(const std::string& driver_board_name) const {
    for (const auto& kv : driver_board) {
        if (kv.second == driver_board_name) return kv.first;
    }
    return driver_board_name;
}

std::string FirmwareDescriptor::driver_board_for(const std::string& gui_board) const {
    auto it = driver_board.find(gui_board);
    return it == driver_board.end() ? gui_board : it->second;
}

namespace {

struct Err {
    const std::string& source;
    std::string& out;
    bool operator()(const std::string& path, const std::string& msg) const {
        out = source + ": " + (path.empty() ? "/" : path) + ": " + msg;
        return false;
    }
};

std::string join_set(const std::set<std::string>& s) {
    std::string r;
    for (const auto& k : s) r += (r.empty() ? "" : ", ") + k;
    return r;
}

// `j` must be an object with every key of `required` and no key outside required + optional.
bool check_object(const Err& fail, const json& j, const std::string& path, const std::set<std::string>& required,
                  const std::set<std::string>& optional = {}) {
    if (!j.is_object()) return fail(path, "expected an object");
    std::set<std::string> all = required;
    all.insert(optional.begin(), optional.end());
    for (auto it = j.begin(); it != j.end(); ++it) {
        if (!all.count(it.key())) return fail(path + "/" + it.key(), "unknown key (allowed: " + join_set(all) + ")");
    }
    for (const std::string& k : required) {
        if (!j.contains(k)) return fail(path + "/" + k, "missing required key");
    }
    return true;
}

bool read_string(const Err& fail, const json& v, const std::string& path, std::string& out) {
    if (!v.is_string()) return fail(path, "expected a string");
    out = v.get<std::string>();
    if (out.empty()) return fail(path, "must not be empty");
    return true;
}

bool read_bool(const Err& fail, const json& v, const std::string& path, bool& out) {
    if (!v.is_boolean()) return fail(path, "expected true or false");
    out = v.get<bool>();
    return true;
}

std::string stem_of(const std::string& path) {
    std::string::size_type slash = path.find_last_of('/');
    std::string base = slash == std::string::npos ? path : path.substr(slash + 1);
    std::string::size_type dot = base.rfind('.');
    return dot == std::string::npos ? base : base.substr(0, dot);
}

}  // namespace

bool FirmwareDescriptor::from_json(const json& j, const std::string& expected_id, const std::string& source,
                                   FirmwareDescriptor& out, std::string& error) {
    const Err fail{source, error};
    FirmwareDescriptor d;

    std::set<std::string> optional = gui_only_keys();
    optional.insert("driver_board");
    if (!check_object(fail, j, "", {"schema", "id", "description", "outputs", "templates", "system_enables", "limits"},
                      optional)) {
        return false;
    }

    {
        const json& v = j.at("schema");
        if (!v.is_number_integer() || v.get<int64_t>() != kSchema) {
            return fail("/schema", "unsupported schema " + v.dump() + " (this driver reads schema " +
                                       std::to_string(kSchema) + ")");
        }
        d.schema = kSchema;
    }
    if (!read_string(fail, j.at("id"), "/id", d.id)) return false;
    if (!expected_id.empty() && d.id != expected_id) {
        return fail("/id", "\"" + d.id + "\" must match the file name \"" + expected_id + "\"");
    }
    if (!read_string(fail, j.at("description"), "/description", d.description)) return false;

    // templates: board -> cfg path; its keys are the boards the firmware supports
    {
        const json& t = j.at("templates");
        if (!t.is_object() || t.empty()) return fail("/templates", "expected a non-empty object (board -> cfg path)");
        for (auto it = t.begin(); it != t.end(); ++it) {
            std::string p;
            if (!read_string(fail, it.value(), "/templates/" + it.key(), p)) return false;
            d.templates[it.key()] = p;
        }
    }

    // outputs: board -> {tlv, lvds}, same board set as templates
    {
        const json& o = j.at("outputs");
        if (!o.is_object()) return fail("/outputs", "expected an object (board -> {tlv, lvds})");
        for (auto it = o.begin(); it != o.end(); ++it) {
            const std::string p = "/outputs/" + it.key();
            if (!d.templates.count(it.key())) return fail(p, "board is not in templates");
            if (!check_object(fail, it.value(), p, {"tlv", "lvds"})) return false;
            Output out_v;
            if (!read_bool(fail, it.value().at("tlv"), p + "/tlv", out_v.tlv) ||
                !read_bool(fail, it.value().at("lvds"), p + "/lvds", out_v.lvds)) {
                return false;
            }
            d.outputs[it.key()] = out_v;
        }
        for (const auto& kv : d.templates) {
            if (!d.outputs.count(kv.first)) return fail("/outputs/" + kv.first, "missing: board is in templates");
        }
    }

    // driver_board: optional, board -> driver board
    if (j.contains("driver_board")) {
        const json& db = j.at("driver_board");
        if (!db.is_object()) return fail("/driver_board", "expected an object (board -> driver board)");
        std::set<std::string> targets;
        for (auto it = db.begin(); it != db.end(); ++it) {
            const std::string p = "/driver_board/" + it.key();
            std::string v;
            if (!d.templates.count(it.key())) return fail(p, "board is not in templates");
            if (!read_string(fail, it.value(), p, v)) return false;
            if (!targets.insert(v).second) return fail(p, "driver board \"" + v + "\" is mapped twice");
            d.driver_board[it.key()] = v;
        }
    }

    // system_enables
    {
        const json& s = j.at("system_enables");
        if (!check_object(fail, s, "/system_enables", {"serial", "dca1000"}) ||
            !read_bool(fail, s.at("serial"), "/system_enables/serial", d.enable_serial) ||
            !read_bool(fail, s.at("dca1000"), "/system_enables/dca1000", d.enable_dca1000)) {
            return false;
        }
    }

    // limits: board -> name -> {value, level, source, confidence}. Names are free-form (the set grows
    // with the firmware matrix); the entry shape is strict.
    {
        const json& l = j.at("limits");
        if (!l.is_object()) return fail("/limits", "expected an object (board -> limits)");
        static const std::set<std::string> confidences = {"repo", "high", "medium", "low", "recalled", "unverified"};
        for (auto bt = l.begin(); bt != l.end(); ++bt) {
            const std::string bp = "/limits/" + bt.key();
            if (!d.templates.count(bt.key())) return fail(bp, "board is not in templates");
            if (!bt.value().is_object()) return fail(bp, "expected an object (limit name -> entry)");
            BoardLimits& bl = d.limits[bt.key()];
            for (auto lt = bt.value().begin(); lt != bt.value().end(); ++lt) {
                const std::string lp = bp + "/" + lt.key();
                if (!check_object(fail, lt.value(), lp, {"value", "level", "source", "confidence"})) return false;
                Limit lim;
                lim.value = lt.value().at("value");
                if (lim.value.is_null() || lim.value.is_object()) {
                    return fail(lp + "/value", "expected a number, boolean, string or array");
                }
                if (!read_string(fail, lt.value().at("level"), lp + "/level", lim.level)) return false;
                if (lim.level != "error" && lim.level != "warning") {
                    return fail(lp + "/level", "\"" + lim.level + "\" is not one of: error, warning");
                }
                if (!read_string(fail, lt.value().at("source"), lp + "/source", lim.source)) return false;
                if (!read_string(fail, lt.value().at("confidence"), lp + "/confidence", lim.confidence)) return false;
                if (!confidences.count(lim.confidence)) {
                    return fail(lp + "/confidence", "\"" + lim.confidence + "\" is not one of: " + join_set(confidences));
                }
                bl[lt.key()] = lim;
            }
        }
    }

    out = d;
    return true;
}

bool FirmwareDescriptor::load(const std::string& path, FirmwareDescriptor& out, std::string& error) {
    std::ifstream f(path);
    if (!f.is_open()) {
        error = path + ": cannot open firmware descriptor";
        return false;
    }
    json j;
    if (!parse_json_strict(f, path, j, error)) return false;
    return from_json(j, stem_of(path), path, out, error);
}

bool FirmwareDescriptor::load_by_id(const std::string& firmware_dir, const std::string& id, FirmwareDescriptor& out,
                                    std::string& error) {
    if (id.empty() || id.find('/') != std::string::npos || id.find('.') != std::string::npos) {
        error = "firmware id \"" + id + "\" must be a plain id such as demo (no path or extension)";
        return false;
    }
    return load(firmware_dir + "/" + id + ".json", out, error);
}

}  // namespace radar
}  // namespace cpsl
