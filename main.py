"""
QSForge - Desktop entry point.
Starts the Flask server on a background thread and opens a pywebview window.

Usage:
    python main.py
    python main.py --debug    # enables DevTools and verbose logging
"""

import os
import shutil
import sys
import time
import threading
import traceback
import urllib.request
import urllib.error
import subprocess
from datetime import datetime
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).parent / "src"))

import server
import paths as app_paths


# Stable AppUserModelID so Windows taskbar groups our window under "QSForge"
# instead of lumping us with every other python.exe that happens to be running.
# Keep the form "CompanyName.AppName.SubProduct.Version" per MSDN guidance.
APP_USER_MODEL_ID = "QSForge.Desktop.RVTQualityCheck.1"


# ── Crash logging ───────────────────────────────────────────────────────────
# When the app is double-clicked from Explorer, stdout/stderr are not attached
# to any visible console. Install a last-resort hook so any unhandled exception
# is written to <exe_dir>\qsforge_crash.log — giving us something to inspect
# even if the window never appears.
_CRASH_LOG_PATH = app_paths.user_data_dir() / "qsforge_crash.log"


def _write_crash(prefix: str, exc_type, exc_value, exc_tb) -> None:
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n===== {datetime.now().isoformat()}  [{prefix}] =====\n")
            f.write(f"frozen={app_paths.is_frozen()}  argv={sys.argv}  cwd={os.getcwd()}\n")
            f.write(text)
    except Exception:
        pass


def _install_crash_hook() -> None:
    def _hook(exc_type, exc_value, exc_tb):
        _write_crash("unhandled", exc_type, exc_value, exc_tb)
        # Fall through to the default handler so the console (when present)
        # still sees the traceback.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _thread_hook(args):
            _write_crash(
                f"thread:{args.thread.name}",
                args.exc_type, args.exc_value, args.exc_traceback,
            )
        threading.excepthook = _thread_hook


def _boot_marker(stage: str) -> None:
    """Write a 'we reached stage X' breadcrumb to the crash log."""
    try:
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[{datetime.now().isoformat()}] boot: {stage}\n")
    except Exception:
        pass


# Keep all WebView2 state in a local, per-app folder so we can wipe it cleanly
# on each launch. Prevents WebView2 from serving a stale index.html/JS from its
# disk cache even after we rebuild the frontend.
_WEBVIEW_DATA_DIR = app_paths.user_data_dir() / ".webview-data"


def _reset_webview_cache():
    """Delete WebView2's per-app data so frontend changes are always picked up.
    Silent no-op if the folder doesn't exist or is locked."""
    if _WEBVIEW_DATA_DIR.exists():
        shutil.rmtree(_WEBVIEW_DATA_DIR, ignore_errors=True)
    try:
        _WEBVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(_WEBVIEW_DATA_DIR)


WINDOW_TITLE = "QSForge — Revit Model Quality Check"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820
HEALTH_URL = f"http://{server.HOST}:{server.PORT}/api/health"
APP_URL = f"http://{server.HOST}:{server.PORT}/"


# ── Windows-native icon + taskbar grouping ──────────────────────────────────
def _set_app_user_model_id() -> None:
    """Give this process its own taskbar identity.

    Without this, Windows groups our pywebview window under the generic
    ``python.exe`` icon in the taskbar (and uses that tiny Python logo).
    Must be called *before* the first window is created."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(APP_USER_MODEL_ID)
        )
    except Exception:
        # Non-fatal — worst case the taskbar shows the wrong icon in dev mode.
        pass


def _find_icon_path() -> Path | None:
    """Locate qsforge.ico whether we're frozen or running from source."""
    candidates = [
        app_paths.resource_dir() / "assets" / "qsforge.ico",
        Path(__file__).resolve().parent / "assets" / "qsforge.ico",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _apply_native_icon(window=None) -> None:
    """Replace the default window icon with QSForge's brand icon.

    pywebview on Windows hands us a standard HWND owned by python.exe, so the
    title bar + Alt-Tab icon default to the Python logo when running from
    source. We override it at runtime via WM_SETICON so dev and packaged
    builds look identical.

    Runs on the shown event so the HWND is already materialised. Safe to call
    more than once (Windows just replaces the icon handle)."""
    if sys.platform != "win32":
        return
    ico = _find_icon_path()
    if not ico:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        def _load(size_px: int):
            return user32.LoadImageW(
                None, str(ico), IMAGE_ICON,
                size_px, size_px,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )

        hicon_big = _load(32)
        hicon_small = _load(16)
        if not (hicon_big or hicon_small):
            return

        # Our window title is unique, so FindWindowW is a reliable way to
        # pick up the HWND that works across every pywebview backend /
        # version without touching private attributes.
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return

        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
    except Exception:
        # Cosmetic only — never block app launch.
        pass


# ── JS-exposed API ──────────────────────────────────────────────────────────
class Api:
    """Methods on this class are callable from the frontend as window.pywebview.api.*"""

    def pick_rvt(self):
        """Open a native file dialog, return absolute path or None."""
        fd_open = getattr(webview, "FileDialog", None)
        fd_type = fd_open.OPEN if fd_open else webview.OPEN_DIALOG
        result = webview.windows[0].create_file_dialog(
            fd_type,
            allow_multiple=False,
            file_types=("Revit files (*.rvt)", "All files (*.*)"),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        return str(Path(path).resolve())

    def get_dropped_rvt(self, paths):
        """Given a list of paths (from an HTML5 drop event via js_api), return the first .rvt."""
        if not paths:
            return None
        for raw in paths:
            p = Path(raw)
            if p.is_file() and p.suffix.lower() == ".rvt":
                return str(p.resolve())
        return None

    def open_in_explorer(self, path):
        """Reveal a file or folder in Windows Explorer."""
        if not path:
            return False
        p = Path(path)
        if not p.exists():
            return False
        try:
            if p.is_dir():
                subprocess.Popen(["explorer", str(p)])
            else:
                subprocess.Popen(["explorer", "/select,", str(p)])
            return True
        except OSError:
            return False

    def open_path(self, path):
        """Open a file with its default Windows handler (e.g. .json → editor)."""
        if not path:
            return False
        p = Path(path)
        if not p.exists():
            return False
        try:
            import os
            os.startfile(str(p))  # noqa: S606 — Windows-only, intended
            return True
        except (OSError, AttributeError):
            return False

    def quit_app(self, delay_ms=1500):
        """
        Close the pywebview window so an external installer can overwrite
        QSForge.exe without "file in use" errors.

        Called by the frontend right after POST /api/updates/apply succeeds
        for the QSForge component. We schedule the close on a short delay
        so the JS side has a chance to finish its in-flight HTTP response
        and show a "closing — please wait" toast.
        """
        delay = max(0, int(delay_ms or 0)) / 1000.0

        def _do_close():
            time.sleep(delay)
            try:
                webview.windows[0].destroy()
            except Exception:
                pass
            # Belt-and-braces: the Flask thread is daemonised, so process
            # exit will reap it. os._exit avoids any atexit hooks that
            # might block the upgrade installer waiting on us.
            time.sleep(0.5)
            os._exit(0)

        threading.Thread(target=_do_close, daemon=True,
                         name="qsforge-quit-for-update").start()
        return True

    def save_pdf_dialog(self, suggested_name="QSForge_Report.pdf"):
        """Open a native Save As dialog for a PDF file. Returns absolute path or None."""
        fd_open = getattr(webview, "FileDialog", None)
        fd_type = fd_open.SAVE if fd_open else webview.SAVE_DIALOG
        try:
            result = webview.windows[0].create_file_dialog(
                fd_type,
                save_filename=suggested_name,
                file_types=("PDF files (*.pdf)", "All files (*.*)"),
            )
        except Exception:
            return None
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        p = Path(path)
        if p.suffix.lower() != ".pdf":
            p = p.with_suffix(".pdf")
        return str(p.resolve())


# ── Server bootstrap ────────────────────────────────────────────────────────
def start_server():
    t = threading.Thread(target=server.main, name="qsforge-server", daemon=True)
    t.start()
    return t


def wait_for_server(timeout=15.0):
    """Ping /api/health until it responds or timeout elapses."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"QSForge server did not become ready in {timeout}s ({last_err})")


# ── Entry ───────────────────────────────────────────────────────────────────
def main():
    _install_crash_hook()
    debug = "--debug" in sys.argv[1:]

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if _stream is None:     # windowed mode: no stdout/stderr at all
                continue
            try:
                _stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError, OSError):
                pass

    _boot_marker("main() entered")
    # Must run BEFORE any window is created so Windows uses our AppUserModelID
    # from the very first taskbar entry (no python.exe flicker).
    _set_app_user_model_id()
    _reset_webview_cache()
    _boot_marker("webview cache reset")
    start_server()
    _boot_marker("flask thread started")
    wait_for_server()
    _boot_marker("server responded to /api/health")

    api = Api()
    url = f"{APP_URL}?_ts={int(time.time())}"
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(960, 640),
        background_color="#070B14",
        text_select=True,
    )

    # Hook the 'shown' event to swap in our brand icon as soon as the HWND
    # exists. Also retry a beat later in case the first attempt hits before
    # the window is fully realised (race with WebView2 init).
    try:
        window.events.shown += lambda: _apply_native_icon(window)
    except Exception:
        pass

    def _delayed_icon_retry():
        # Give the window a second to fully initialise, then re-apply. This
        # catches the case where WebView2's warm-up replaces the HWND icon
        # after our shown-event handler has already run.
        time.sleep(1.0)
        _apply_native_icon()
        time.sleep(2.0)
        _apply_native_icon()

    threading.Thread(target=_delayed_icon_retry, daemon=True,
                     name="qsforge-icon-retry").start()

    _boot_marker("window created, calling webview.start()")
    try:
        webview.start(debug=debug, private_mode=True)
    except TypeError:
        webview.start(debug=debug)
    _boot_marker("webview.start() returned (window closed)")


if __name__ == "__main__":
    main()
