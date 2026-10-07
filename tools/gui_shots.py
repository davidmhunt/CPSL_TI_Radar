"""Headless-Firefox screenshot driver for the radar GUI (stdlib only).

Drives the installed Firefox through geckodriver's WebDriver HTTP API using
only urllib/json/subprocess (no new dependency), starts
``python -m radar_gui --source mock`` (or attaches to ``--url``), opens the
Configure tab, runs scenarios and saves PNGs.

    uv run python tools/gui_shots.py --scenarios builtin --out /some/dir
    uv run python tools/gui_shots.py --scenarios my.json --url http://127.0.0.1:8000

Spec: a JSON list of scenarios, or {"user_cfgs": {"name.cfg": "<text>"}, "env": {...}, "scenarios": [...]}
(user_cfgs appear in the picker as saved cfgs, for cfgs not shipped; a name.json is a system JSON for the Run tab, and
"@PORT@" in any user_cfgs text becomes a scratch file that exists, for "cli.port"; "env" is added to the server's
environment, e.g. FAKE_DRIVER_MODE, RADAR_GUI_DRIVER=tests/fakes/fake_driver.py; or pass --driver-bin); each scenario (optional "tab":
"run" opens the Run tab instead of Configure):
    {"name": "x", "window": [1400, 2400],           # optional; "fresh": false keeps the previous page state;
                                                   # "expand": false disables un-clipping the scrolling columns
     "actions": [ ... ],
     "shots": [{"file": "x.png", "selector": "#mimoCard"}],   # selector optional
                                                   # -> element shot; omitted -> full page
     "dumps": [{"file": "x.txt", "selector": "#l_data_fmt", "what": "options"}]}
                                                   # what: options | text | html | overflow | values (visible inputs/selects as id = value)
Actions (each followed by a short settle delay for the debounced re-analysis):
    {"mode": "direct"|"targets"}                  click the Targets/Chirp-parameters switch
    {"board": "IWR1843"}  {"firmware": "text"}    select by value or option text (substring)
    {"load": "cascade_shortrange"}                pick a cfg in #cLoad (substring of text/value)
    {"set": "#id", "value": "10000"}              set input/select, dispatch input+change
    {"click": "#id"}   {"wait": 1.5}
    {"click_text": "BPM (2 TX)", "within": "#mChirpTable", "times": 1}   click a button by its text   {"js": "return document.title"}
The app is a fixed-height layout whose columns scroll internally, so use a tall
window (default 1400x2400) when shooting an element or the whole page.
Outputs go under --out/<scenario name>/ ; the default --out is
<repo root>/gui_shots/<spec name> (gitignored; PNG bytes come back over WebDriver
and Python writes them, so snap Firefox never touches the path). Never commit PNGs.
Console errors (window error / unhandledrejection / console.error captured after
page load) are written to <out>/console_errors.txt.
"""
import argparse, base64, json, os, shutil, signal, socket, subprocess, sys, tempfile, time
import urllib.request, urllib.error

GECKO = shutil.which("geckodriver") or "/snap/bin/geckodriver"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTLE = 1.0

BUILTIN = [
    {"name": "default", "window": [1400, 1000], "actions": [],
     "shots": [{"file": "full.png"}]},
]

HOOK = """
window.__errs = window.__errs || [];
if (!window.__hooked) { window.__hooked = true;
 window.addEventListener('error', e => window.__errs.push('error: ' + e.message + ' @' + e.filename + ':' + e.lineno));
 window.addEventListener('unhandledrejection', e => window.__errs.push('rejection: ' + (e.reason && e.reason.stack || e.reason)));
 const ce = console.error; console.error = function(...a){ window.__errs.push('console.error: ' + a.join(' ')); ce.apply(console, a); };
}
"""


def load_spec(path):
    """Return (scenarios, user_cfgs). user_cfgs: {filename: cfg text} shown in the GUI's saved-cfg list."""
    if path == "builtin":
        return BUILTIN, {}
    with open(path) as f:
        spec = json.load(f)
    user = {}
    if isinstance(spec, dict):
        user = spec.get("user_cfgs", {})
        spec = spec["scenarios"]
    for s in spec:
        if "name" not in s:
            raise ValueError("scenario without a name: %r" % (s,))
    return spec, user


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> %s %s" % (method, url, e.code, e.read()[:400]))


def wait_url(url, tries=100):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("not reachable: " + url)


class Driver:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port
        self.sid = None

    def cmd(self, method, path, body=None):
        return http(method, "%s/session/%s%s" % (self.base, self.sid, path), body)["value"]

    def start(self):
        caps = {"capabilities": {"alwaysMatch": {"browserName": "firefox",
                "moz:firefoxOptions": {"args": ["-headless"]}}}}
        v = http("POST", self.base + "/session", caps, timeout=120)["value"]
        self.sid = v["sessionId"]

    def stop(self):
        if self.sid:
            try:
                http("DELETE", "%s/session/%s" % (self.base, self.sid), timeout=15)
            except Exception:
                pass
            self.sid = None

    def js(self, script, *args):
        return self.cmd("POST", "/execute/sync", {"script": script, "args": list(args)})

    def find(self, sel):
        el = self.cmd("POST", "/element", {"using": "css selector", "value": sel})
        return list(el.values())[0]

    def png(self, path, sel=None):
        if sel:
            b = self.cmd("GET", "/element/%s/screenshot" % self.find(sel))
        else:
            b = self.cmd("GET", "/moz/screenshot/full")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b))


EXPAND_JS = """
const st = document.getElementById('__expand') || document.head.appendChild(document.createElement('style'));
st.id = '__expand';
st.textContent = 'html,body,#cfgMain,#runMain{height:auto!important;max-height:none!important;overflow:visible!important}' +
                 '.cfgcol,.runcol{overflow:visible!important;max-height:none!important}';
"""

SET_JS = """
const el = document.querySelector(arguments[0]); if (!el) return 'missing ' + arguments[0];
const v = String(arguments[1]);
if (el.tagName === 'SELECT') {
  const o = [...el.options].find(o => o.value === v) || [...el.options].find(o => o.text.includes(v) || o.value.includes(v));
  if (!o) return 'no option ' + v + ' in ' + [...el.options].map(o=>o.text).join(' | ');
  el.value = o.value;
} else if (el.type === 'checkbox') { el.checked = (v === '1' || v === 'true'); }
else el.value = v;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
return 'ok';
"""

DUMP_JS = """
const el = document.querySelector(arguments[0]); if (!el) return 'missing ' + arguments[0];
const w = arguments[1];
if (w === 'options') return [...el.options].map(o => (o.selected ? '* ' : '  ') + o.value + ' : ' + o.text).join('\\n');
if (w === 'html') return el.outerHTML;
if (w === 'overflow') { const d = document.documentElement; return 'page scrollWidth ' + d.scrollWidth + ' innerWidth ' + innerWidth + (d.scrollWidth > innerWidth ? ' HORIZONTAL OVERFLOW' : ' ok') + '; element scrollWidth ' + el.scrollWidth + ' clientWidth ' + el.clientWidth + (el.scrollWidth > el.clientWidth ? ' ELEMENT OVERFLOW' : ' ok'); }
if (w === 'values') return [...el.querySelectorAll('input,select')].filter(e => !e.closest('[hidden]') && e.offsetParent).map(e => (e.id || e.name) + ' = ' + (e.type === 'checkbox' ? e.checked : e.value)).join('\\n');
return el.innerText;
"""


def run_action(d, a):
    settle = SETTLE
    if "mode" in a:
        r = d.js("const b=[...document.querySelectorAll('#cInMode button')].find(b=>b.dataset.m===arguments[0]);"
                 "if(!b)return 'missing';b.click();return 'ok'", a["mode"])
    elif "board" in a:
        r = d.js(SET_JS, "#cBoard", a["board"]); settle = 2.0
    elif "firmware" in a:
        r = d.js(SET_JS, "#cFw", a["firmware"])
    elif "load" in a:
        r = d.js(SET_JS, "#cLoad", a["load"]); settle = 2.0
    elif "set" in a:
        r = d.js(SET_JS, a["set"], a.get("value", ""))
    elif "click" in a:
        r = d.js("const e=document.querySelector(arguments[0]);if(!e)return 'missing';e.click();return 'ok'", a["click"])
    elif "click_text" in a:
        r = "ok"
        for _ in range(int(a.get("times", 1))):
            r = d.js("const root=document.querySelector(arguments[0]||'body');if(!root)return 'missing root';"
                     "const b=[...root.querySelectorAll('button')].find(b=>b.textContent.trim()===arguments[1]);"
                     "if(!b)return 'missing button '+arguments[1];if(b.disabled)return 'disabled';b.click();return 'ok'",
                     a.get("within"), a["click_text"])
            time.sleep(0.4)
            if r != "ok":
                break
        if r == "disabled":
            r = "ok"
    elif "js" in a:
        r = d.js(a["js"])
    elif "wait" in a:
        time.sleep(float(a["wait"])); return
    else:
        raise ValueError("unknown action %r" % (a,))
    if isinstance(r, str) and r != "ok" and ("missing" in r or r.startswith("no option")):
        print("  WARN action %s -> %s" % (a, r), file=sys.stderr)
    time.sleep(settle)


def run_scenario(d, sc, out, url):
    if sc.get("fresh", True):   # isolate scenarios: reload the page so no state leaks from the previous one
        d.cmd("POST", "/url", {"url": "about:blank"})
        d.cmd("POST", "/url", {"url": url.rstrip("/") + "/#" + sc.get("tab", "configure")})
        time.sleep(2.5)
        d.js(HOOK)
    sdir = os.path.join(out, sc["name"])
    os.makedirs(sdir, exist_ok=True)
    w, h = sc.get("window", [1400, 2400])
    d.cmd("POST", "/window/rect", {"width": int(w), "height": int(h)})
    for a in sc.get("actions", []):
        run_action(d, a)
    time.sleep(0.3)
    if sc.get("expand", True):   # let the scrolling columns grow so element/full shots are not clipped
        d.js(EXPAND_JS); time.sleep(0.3)
    for s in sc.get("shots", []):
        p = os.path.join(sdir, s["file"]); d.png(p, s.get("selector")); print("  wrote", p)
    for s in sc.get("dumps", []):
        p = os.path.join(sdir, s["file"])
        with open(p, "w") as f:
            f.write(str(d.js(DUMP_JS, s["selector"], s.get("what", "text"))) + "\n")
        print("  wrote", p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default="builtin", help="JSON spec file or 'builtin'")
    ap.add_argument("--out", help="output dir (default: <repo root>/gui_shots/<spec name>)")
    ap.add_argument("--url", help="attach to a running GUI instead of starting one")
    ap.add_argument("--driver-bin", help="driver binary for the Run tab (e.g. tests/fakes/fake_driver.py)")
    ap.add_argument("--only", help="run only scenarios whose name contains this")
    a = ap.parse_args(argv)
    spec, user_cfgs = load_spec(a.scenarios)
    if a.only:
        spec = [s for s in spec if a.only in s["name"]]
    if a.out is None:
        name = "builtin" if a.scenarios == "builtin" else os.path.splitext(os.path.basename(a.scenarios))[0]
        a.out = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "gui_shots", name)
    out = os.path.abspath(os.path.expanduser(a.out)); os.makedirs(out, exist_ok=True)

    procs, d, scratch = [], None, None
    try:
        url = a.url
        if not url:
            port = free_port()
            env = dict(os.environ)
            # Fake-driver runs and serial dumps go to a scratch root, never the repo's runs/gui/ (real bench runs live there).
            scratch = tempfile.mkdtemp(prefix="gui_shots_runs_")
            env["RADAR_GUI_RUN_DIR"] = os.path.join(scratch, "runs")
            env["RADAR_GUI_DUMP_DIR"] = os.path.join(scratch, "dumps")
            if a.scenarios != "builtin":   # optional top-level "env": {NAME: value} for the server (e.g. FAKE_DRIVER_MODE)
                with open(a.scenarios) as f:
                    sp = json.load(f)
                env.update({k: str(v) for k, v in (sp.get("env", {}) if isinstance(sp, dict) else {}).items()})
                if env.get("RADAR_GUI_DRIVER") and not os.path.isabs(env["RADAR_GUI_DRIVER"]):
                    env["RADAR_GUI_DRIVER"] = os.path.join(ROOT, env["RADAR_GUI_DRIVER"])
            if user_cfgs:   # scratch saved-cfg dir for this run only
                udir = os.path.join(out, "_usercfg"); os.makedirs(udir, exist_ok=True)
                fake_port = os.path.join(udir, "fake_port")   # a path that exists and nobody holds, for system JSON "cli.port"
                open(fake_port, "w").close()
                for fn, txt in user_cfgs.items():
                    with open(os.path.join(udir, fn), "w") as f:
                        f.write(txt.replace("@PORT@", fake_port))
                env["RADAR_GUI_USER_CFG_DIR"] = udir
            cmd = ["uv", "run", "python", "-m", "radar_gui", "--source", "mock", "--port", str(port)]
            if a.driver_bin:
                cmd += ["--driver-bin", os.path.abspath(a.driver_bin)]
            procs.append(subprocess.Popen(
                cmd,
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
            url = "http://127.0.0.1:%d" % port
        wait_url(url + "/api/cfgs")
        gport = free_port()
        procs.append(subprocess.Popen([GECKO, "--port", str(gport)], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True))
        wait_url("http://127.0.0.1:%d/status" % gport)
        d = Driver(gport); d.start()
        d.cmd("POST", "/url", {"url": url.rstrip("/") + "/#configure"})
        time.sleep(2.5)
        d.js(HOOK)
        errs = []
        for sc in spec:
            print("scenario", sc["name"])
            try:
                run_scenario(d, sc, out, url)
            except Exception as e:
                print("  FAILED: %s" % e, file=sys.stderr); errs.append("%s: scenario failed: %s" % (sc["name"], e))
            try:
                errs += ["%s: %s" % (sc["name"], x) for x in (d.js("const r=window.__errs||[];window.__errs=[];return r") or [])]
            except Exception:
                pass
        with open(os.path.join(out, "console_errors.txt"), "w") as f:
            f.write("\n".join(errs) + ("\n" if errs else "(none)\n"))
        print("console errors: %d" % len(errs))
        return 0
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
        if d:
            d.stop()
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM); p.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
