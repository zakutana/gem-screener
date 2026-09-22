"""
Gem Screener — local app.

Double-click GemScreener.exe (or run `python app.py`): it starts a loopback-only
web server, opens the browser, and serves the viewer with a Refresh button that
re-runs the collector on demand.

Why a server at all: a published Artifact cannot fetch DeFiLlama (its CSP blocks
external hosts), so data has to be collected locally and embedded. This is that
loop, without needing a Claude session to republish.

Deliberate choices, each one a bug that would otherwise only show at runtime:

  * stdout/stderr are redirected to a log file BEFORE collector is imported.
    PyInstaller's --noconsole sets sys.stdout to None, and every print() in the
    collector would be a silent no-op — errors included.
  * allow_reuse_address = False. The default (1) lets a SECOND instance bind an
    already-listening loopback port without error on Windows; both processes
    then "serve" and connections are lost at random.
  * The snapshot is held in memory and never re-read from disk while serving,
    so os.replace() during a refresh can never hit a PermissionError from our
    own open file handle.
  * A fatal startup error becomes a MessageBox. With no console there is
    otherwise nothing to see: the exe would just not appear.
  * There is no console to Ctrl-C either, so the app exits on /api/quit or after
    IDLE_TIMEOUT with no requests.
"""
import ctypes
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_ID = "gem-screener"
# GEM_PORT pins one port — for testing a new build next to a copy that is already
# running (the default range finds that copy on 8765 and just opens its page).
PORTS = ([int(os.environ["GEM_PORT"])] if os.environ.get("GEM_PORT", "").isdigit()
         else list(range(8765, 8776)))
IDLE_TIMEOUT = 30 * 60      # no requests for this long -> exit
STALE_AFTER = 12 * 3600     # snapshot older than this -> refresh on launch
LOG_NAME = "gem_screener.log"


# ---------------------------------------------------------------- paths
def is_frozen():
    return getattr(sys, "frozen", False)


def bundle_dir():
    """Where read-only assets live (template.html)."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        return False


def pick_data_dir():
    """Where snapshot.json and the log live: next to the exe when that is
    writable, otherwise %LOCALAPPDATA% (exe dropped in Program Files)."""
    base = (os.path.dirname(sys.executable) if is_frozen()
            else os.path.dirname(os.path.abspath(__file__)))
    if _writable(base):
        return base
    fallback = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                            "GemScreener")
    os.makedirs(fallback, exist_ok=True)
    return fallback


BUNDLE_DIR = bundle_dir()
DATA_DIR = pick_data_dir()
SNAPSHOT_PATH = os.path.join(DATA_DIR, "snapshot.json")
TEMPLATE_PATH = os.path.join(BUNDLE_DIR, "template.html")


class _Tee:
    """Write to the log file and, when there is one, the console as well."""

    def __init__(self, logfile, console):
        self.logfile = logfile
        self.console = console

    def write(self, s):
        try:
            self.logfile.write(s)
        except Exception:
            pass
        if self.console is not None:
            try:
                self.console.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        for f in (self.logfile, self.console):
            if f is not None:
                try:
                    f.flush()
                except Exception:
                    pass

    def isatty(self):
        return False


def setup_logging():
    """Must run before collector is imported (see module docstring).

    Under --noconsole sys.stdout is None, so this is the only thing standing
    between a failed refresh and total silence."""
    try:
        f = io.open(os.path.join(DATA_DIR, LOG_NAME), "a", buffering=1, encoding="utf-8")
    except Exception:
        return
    sys.stdout = _Tee(f, sys.stdout)
    sys.stderr = _Tee(f, sys.stderr)
    print("\n=== %s start (pid %d, data=%s, frozen=%s) ==="
          % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), DATA_DIR, is_frozen()))


setup_logging()

import build_viewer                                    # noqa: E402
import collector                                       # noqa: E402


def die(msg):
    """No console means a traceback goes nowhere the user will look."""
    print("FATAL: %s" % msg)
    try:
        ctypes.windll.user32.MessageBoxW(0, str(msg), "Gem Screener", 0x10)
    except Exception:
        pass
    sys.exit(1)


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.started_at = None
        self.lines = deque(maxlen=200)
        self.error = None
        self.snapshot_text = None
        self.generated_at = None
        self.last_seen = time.time()

    def load_from_disk(self):
        try:
            text = io.open(SNAPSHOT_PATH, encoding="utf-8").read()
            self.snapshot_text = text
            self.generated_at = json.loads(text).get("generated_at")
        except Exception as e:
            print("no usable snapshot yet (%s)" % e)
            self.snapshot_text = json.dumps({
                "generated_at": 0, "generated_at_iso": "", "windows": [30, 90, 180, 365],
                "collection_floor_usd_30d": collector.COLLECTION_FLOOR_USD_30D,
                "apps": [], "chains": [], "sectors": {"apps": [], "chains": []},
                "excluded": {},
            })
            self.generated_at = None

    def age_seconds(self):
        return None if not self.generated_at else time.time() - self.generated_at

    def add_line(self, msg):
        with self.lock:
            self.lines.append(msg)
        print(msg)

    def status(self):
        with self.lock:
            return {
                "app": APP_ID,
                "running": self.running,
                "started_at": self.started_at,
                "lines": list(self.lines)[-30:],
                "generated_at": self.generated_at,
                "error": self.error,
            }


STATE = State()


def do_refresh():
    try:
        snap = collector.run(log=STATE.add_line, data_dir=DATA_DIR)
        text = json.dumps(snap, separators=(",", ":"), ensure_ascii=False)
        with STATE.lock:
            STATE.snapshot_text = text
            STATE.generated_at = snap.get("generated_at")
            STATE.error = None
    except Exception as e:
        import traceback
        traceback.print_exc()
        with STATE.lock:
            STATE.error = "%s: %s" % (type(e).__name__, e)
        STATE.add_line("  ! refresh failed: %s" % STATE.error)
    finally:
        with STATE.lock:
            STATE.running = False


def start_refresh():
    """Returns False if one is already in flight."""
    with STATE.lock:
        if STATE.running:
            return False
        STATE.running = True
        STATE.started_at = int(time.time())
        STATE.error = None
        STATE.lines.clear()
    threading.Thread(target=do_refresh, daemon=True).start()
    return True


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "GemScreener/11"

    def log_message(self, fmt, *args):
        pass          # the collector's own log is the interesting one

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Without this, a reload after a refresh can serve the pre-refresh page.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def do_GET(self):
        STATE.last_seen = time.time()
        path = self.path.split("?")[0]
        if path == "/api/status":
            return self._send(200, json.dumps(STATE.status()))
        if path in ("/", "/index.html"):
            return self._send(200, render_page(), "text/html; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        STATE.last_seen = time.time()
        path = self.path.split("?")[0]
        if path == "/api/refresh":
            if start_refresh():
                return self._send(202, json.dumps({"started": True}))
            return self._send(409, json.dumps({"error": "refresh already running"}))
        if path == "/api/quit":
            self._send(200, json.dumps({"bye": True}))
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)),
                             daemon=True).start()
            return
        return self._send(404, json.dumps({"error": "not found"}))


def render_page():
    tpl = io.open(TEMPLATE_PATH, encoding="utf-8").read()
    with STATE.lock:
        snap = STATE.snapshot_text
    return build_viewer.inject(tpl, snap, served=True)


class Server(ThreadingHTTPServer):
    # See module docstring: the default of 1 lets a second instance bind a live
    # loopback port silently, and then neither process reliably gets requests.
    allow_reuse_address = False
    daemon_threads = True


def existing_instance(port):
    """True only if OUR app already answers there."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/status" % port, timeout=1) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == APP_ID
    except Exception:
        return False


def bind_server():
    for port in PORTS:
        if existing_instance(port):
            return None, port           # already ours -> just open the browser
        try:
            return Server(("127.0.0.1", port), Handler), port
        except OSError:
            continue                    # taken by something else, try the next
    return None, None


def idle_watchdog():
    while True:
        time.sleep(60)
        with STATE.lock:
            busy = STATE.running
        if not busy and time.time() - STATE.last_seen > IDLE_TIMEOUT:
            print("idle for %d min, exiting" % (IDLE_TIMEOUT // 60))
            os._exit(0)


def open_browser(url):
    # GEM_NO_BROWSER=1 serves without opening a tab — for driving the exe end to
    # end in a test without taking over the desktop it runs on.
    if not os.environ.get("GEM_NO_BROWSER"):
        webbrowser.open(url)


def main():
    if not os.path.exists(TEMPLATE_PATH):
        die("template.html not found at %s" % TEMPLATE_PATH)

    srv, port = bind_server()
    if port is None:
        die("no free port in %d-%d" % (PORTS[0], PORTS[-1]))
    url = "http://127.0.0.1:%d/" % port
    if srv is None:
        print("already running on %s — opening browser" % url)
        open_browser(url)
        return

    STATE.load_from_disk()
    age = STATE.age_seconds()
    print("serving %s (data %s)"
          % (url, "missing" if age is None else "%.1f h old" % (age / 3600.0)))

    # Bind + listen already happened in the constructor, so the browser can
    # connect before serve_forever starts accepting — no race.
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=idle_watchdog, daemon=True).start()
    open_browser(url)

    if age is None or age > STALE_AFTER:
        print("snapshot missing or stale -> refreshing on launch")
        start_refresh()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("interrupted, exiting")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(exc)
