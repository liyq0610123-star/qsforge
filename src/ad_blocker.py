"""
QSForge — DDC Ad-window Blocker

DDC Community Edition (RvtExporter.exe) forces the default browser open to
promo pages on every conversion:

    https://datadrivenconstruction.io/ddc_thank-you/
    https://datadrivenconstruction.io/go-to-the-full-version/?utm_content=…

Closing that nag is a paid feature in DDC's "Ad-Free Full edition". Rather
than making our users pay DDC for that, we handle it ourselves:

  1) Snapshot the set of top-level window handles BEFORE DDC runs.

  2) Poll the window list while DDC runs AND for a grace period afterwards
     (browsers often finish opening the URL 1–3 s after DDC exits).

  3) Any NEW top-level window whose title contains a DDC promo keyword is
     closed with WM_CLOSE. If a new window's title hasn't matched yet (the
     tab is still "New Tab" or "Loading..."), we keep re-checking it for
     up to 30 s before giving up.

  4) If the promo page opens as a new TAB inside an already-existing browser
     window (i.e. no new top-level HWND appears, only the window title of
     an existing browser changes), we *cannot* close just that tab without
     injecting keystrokes into the user's foreground — which is intrusive.
     We log a one-time hint pointing to tools/block_ddc_ads.bat, which
     blocks the DDC domains at the Windows hosts-file level (root-cause fix).

Pure ctypes (user32 / kernel32) — no extra dependencies, no admin rights.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes, Structure, Union, POINTER, byref, sizeof
from typing import Callable, Iterable, Optional

# ── Win32 bindings ──────────────────────────────────────────────────────────
_USER32: Optional[ctypes.WinDLL] = None
_KERNEL32: Optional[ctypes.WinDLL] = None
if sys.platform == "win32":
    try:
        _USER32 = ctypes.windll.user32  # type: ignore[attr-defined]
        _KERNEL32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        _USER32 = None
        _KERNEL32 = None

_WM_CLOSE = 0x0010

# --- SendInput plumbing for the "steal focus + Ctrl+W" fallback ------------
# Used when the DDC promo page lands as a new TAB inside an already-open
# browser. WM_CLOSE would close the entire browser window (and every tab
# inside it). Ctrl+W closes only the active tab, which is the DDC tab.
_ULONG_PTR = ctypes.c_size_t

_VK_CONTROL = 0x11
_VK_W = 0x57
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1


class _KEYBDINPUT(Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


if _USER32 is not None:
    # Tight prototype so ctypes doesn't mangle the pointer / UINT.
    _USER32.SendInput.argtypes = (wintypes.UINT, POINTER(_INPUT), ctypes.c_int)
    _USER32.SendInput.restype = wintypes.UINT
    _USER32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _USER32.SetForegroundWindow.restype = wintypes.BOOL
    _USER32.GetForegroundWindow.restype = wintypes.HWND
    _USER32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _USER32.AttachThreadInput.restype = wintypes.BOOL
    _USER32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, POINTER(wintypes.DWORD))
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _USER32.BringWindowToTop.argtypes = (wintypes.HWND,)
    _USER32.BringWindowToTop.restype = wintypes.BOOL
    _USER32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, _ULONG_PTR)
    _USER32.keybd_event.restype = None

# Case-insensitive substrings that positively identify a DDC promo window.
# These appear in the HTML <title> of the promo pages, and therefore in the
# browser's top-level window title when that tab is active. They are very
# unlikely to collide with legitimate user-owned windows.
AD_KEYWORDS: tuple[str, ...] = (
    "datadrivenconstruction",
    "ddc_thank-you",
    "go-to-the-full-version",
)

# How long to keep re-checking a new window that didn't match on first sight.
# Browsers frequently open a blank tab ("New Tab") and load the actual URL a
# second or two later — the title only reflects the promo page after load.
_NEW_WINDOW_GRACE_SEC = 30.0


# ── Win32 helpers ───────────────────────────────────────────────────────────
def _is_windows() -> bool:
    return _USER32 is not None


def _list_top_windows() -> set[int]:
    """Visible top-level HWNDs. Empty set off-Windows."""
    if _USER32 is None:
        return set()
    out: set[int] = set()
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd: int, _: int) -> bool:
        try:
            if _USER32.IsWindowVisible(hwnd):
                out.add(int(hwnd))
        except OSError:
            pass
        return True

    try:
        _USER32.EnumWindows(EnumWindowsProc(_cb), 0)
    except OSError:
        pass
    return out


def _get_title(hwnd: int) -> str:
    if _USER32 is None:
        return ""
    try:
        length = _USER32.GetWindowTextLengthW(hwnd)
    except OSError:
        return ""
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    try:
        _USER32.GetWindowTextW(hwnd, buf, length + 1)
    except OSError:
        return ""
    return buf.value or ""


def _title_matches(title: str, keywords: Iterable[str]) -> bool:
    if not title:
        return False
    low = title.lower()
    return any(kw in low for kw in keywords)


def _close_window(hwnd: int) -> None:
    if _USER32 is None:
        return
    try:
        _USER32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    except OSError:
        pass


def _send_ctrl_w_to_foreground() -> None:
    """SendInput a Ctrl+W keystroke to whatever currently has focus."""
    if _USER32 is None:
        return
    seq = (_INPUT * 4)()
    spec = [
        (_VK_CONTROL, False),
        (_VK_W, False),
        (_VK_W, True),
        (_VK_CONTROL, True),
    ]
    for i, (vk, keyup) in enumerate(spec):
        seq[i].type = _INPUT_KEYBOARD
        seq[i].u.ki.wVk = wintypes.WORD(vk)
        seq[i].u.ki.wScan = wintypes.WORD(0)
        seq[i].u.ki.dwFlags = wintypes.DWORD(
            _KEYEVENTF_KEYUP if keyup else 0
        )
        seq[i].u.ki.time = wintypes.DWORD(0)
        seq[i].u.ki.dwExtraInfo = _ULONG_PTR(0)
    try:
        _USER32.SendInput(4, seq, sizeof(_INPUT))
    except OSError:
        pass


def _force_foreground(hwnd: int) -> bool:
    """
    Make `hwnd` the foreground window, working around Windows' focus-stealing
    protection. Returns True on success.
    """
    if _USER32 is None or _KERNEL32 is None or not hwnd:
        return False

    # The "null keystroke" trick: Windows only allows foreground changes when
    # it believes the calling thread has just received user input. Firing a
    # dummy keybd_event primes that condition for SetForegroundWindow.
    try:
        _USER32.keybd_event(0, 0, 0, _ULONG_PTR(0))
    except OSError:
        pass

    try:
        if _USER32.SetForegroundWindow(hwnd):
            return True
    except OSError:
        pass

    # Fallback: attach our input queue to the target's thread, which lets
    # SetForegroundWindow succeed even without the keystroke prime.
    try:
        our_tid = _KERNEL32.GetCurrentThreadId()
        tgt_tid = _USER32.GetWindowThreadProcessId(hwnd, None)
        if tgt_tid == 0 or tgt_tid == our_tid:
            return False
        if not _USER32.AttachThreadInput(our_tid, tgt_tid, True):
            return False
        try:
            _USER32.BringWindowToTop(hwnd)
            ok = bool(_USER32.SetForegroundWindow(hwnd))
        finally:
            _USER32.AttachThreadInput(our_tid, tgt_tid, False)
        return ok
    except OSError:
        return False


def _close_active_tab_via_ctrl_w(hwnd: int) -> bool:
    """
    Focus the given browser window briefly, fire Ctrl+W to close the active
    tab (which is the DDC promo tab — browsers open ShellExecute URLs as
    foreground tabs), then hand focus back to whoever had it before.

    This DOES cause the target window to flash to the front for ~150 ms;
    that's the price of closing only the offending tab rather than the
    whole browser window.
    """
    if _USER32 is None or not hwnd:
        return False

    prev_fg = 0
    try:
        prev_fg = int(_USER32.GetForegroundWindow() or 0)
    except OSError:
        prev_fg = 0

    if not _force_foreground(hwnd):
        return False

    # Give the OS a hair to actually route focus to the browser's render
    # widget. Without this the SendInput sometimes lands in a window that
    # is mid-activation.
    time.sleep(0.04)
    _send_ctrl_w_to_foreground()
    time.sleep(0.08)

    # Best-effort: put focus back where it was. If the user was on their
    # desktop / Windows Explorer / IDE, they shouldn't even notice.
    if prev_fg and prev_fg != hwnd:
        try:
            _force_foreground(prev_fg)
        except OSError:
            pass

    return True


# ── Public API ──────────────────────────────────────────────────────────────
def _noop(_msg: str) -> None:
    pass


class AdWindowWatcher:
    """
    Context manager. Snapshots windows on ``__enter__``, runs a background
    daemon thread that closes DDC-promo windows, and keeps watching for
    ``tail_seconds`` after ``__exit__`` (browsers often finish opening the
    URL a moment after DDC itself exits).

    ``__exit__`` does NOT block the caller.

    Environment-variable override:
        QSFORGE_ALLOW_DDC_ADS=1   disables the watcher entirely.

    Usage:
        with AdWindowWatcher(log=logger.info):
            subprocess.run([...ddc...])
    """

    def __init__(
        self,
        log: Optional[Callable[[str], None]] = None,
        poll_interval: float = 0.15,
        tail_seconds: float = 15.0,
        keywords: Optional[Iterable[str]] = None,
    ):
        self.log = log or _noop
        self.poll_interval = max(0.05, float(poll_interval))
        self.tail_seconds = max(0.0, float(tail_seconds))
        self._keywords = tuple(keywords) if keywords else AD_KEYWORDS
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Windows that existed before DDC started. We DO NOT close these, but
        # we do watch their titles — if a baseline browser title flips to a
        # DDC page we log a hint (see _handle_baseline_hit).
        self._baseline: set[int] = set()
        self._baseline_titles: dict[int, str] = {}

        # Windows that appeared after DDC started. Each value is the first
        # time we saw them. We poll their titles until either (a) we match
        # and close, or (b) _NEW_WINDOW_GRACE_SEC elapses and we give up.
        self._pending_new: dict[int, float] = {}

        self._closed_count = 0
        self._deadline: Optional[float] = None
        self._enabled = _is_windows() and not self._opt_out()
        # Same hwnd may be closed again 10s later if DDC opens a second page
        # (it opens two: thank-you + go-to-full-version), but not much more
        # often than that — avoids pathological Ctrl+W storms.
        self._last_tab_close: dict[int, float] = {}
        # Master switch for the foreground-stealing fallback. Users who find
        # the ~150ms flash annoying can set QSFORGE_NO_CTRLW=1 to get back
        # the "log-only" behavior.
        self._allow_ctrl_w = os.environ.get(
            "QSFORGE_NO_CTRLW", ""
        ).strip().lower() not in {"1", "true", "yes", "on"}

    @staticmethod
    def _opt_out() -> bool:
        return os.environ.get("QSFORGE_ALLOW_DDC_ADS", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    def __enter__(self) -> "AdWindowWatcher":
        if not self._enabled:
            return self
        try:
            self._baseline = _list_top_windows()
            self._baseline_titles = {h: _get_title(h) for h in self._baseline}
        except OSError:
            self._baseline = set()
            self._baseline_titles = {}
        self._thread = threading.Thread(
            target=self._run,
            name="QSForge-AdWatcher",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._enabled:
            # Grace period AFTER DDC has exited — browsers often load the
            # URL a couple of seconds later.
            self._deadline = time.monotonic() + self.tail_seconds
        return False

    # ── Internals ────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            if self._deadline is not None and time.monotonic() >= self._deadline:
                break
            try:
                self._sweep_once()
            except Exception:
                # The watcher must never crash the caller.
                pass
            time.sleep(self.poll_interval)

        if self._closed_count:
            try:
                self.log(
                    f"Suppressed {self._closed_count} DDC promo window(s)"
                )
            except Exception:
                pass

    def _sweep_once(self) -> None:
        now = time.monotonic()
        current = _list_top_windows()

        # 1) Process windows we're already tracking as "new" — their title
        #    may have just finished loading.
        for hwnd in list(self._pending_new.keys()):
            if hwnd not in current:
                # Window closed on its own (e.g. user closed the tab/window).
                self._pending_new.pop(hwnd, None)
                continue
            title = _get_title(hwnd)
            if _title_matches(title, self._keywords):
                _close_window(hwnd)
                self._closed_count += 1
                self._pending_new.pop(hwnd, None)
                continue
            # Still loading. Give up once the grace period elapses; promote
            # to baseline so we don't hammer it forever.
            first_seen = self._pending_new[hwnd]
            if now - first_seen > _NEW_WINDOW_GRACE_SEC:
                self._pending_new.pop(hwnd, None)
                self._baseline.add(hwnd)
                self._baseline_titles[hwnd] = title

        # 2) Look for NEW top-level windows (appeared after our snapshot).
        for hwnd in current - self._baseline - set(self._pending_new):
            title = _get_title(hwnd)
            if _title_matches(title, self._keywords):
                _close_window(hwnd)
                self._closed_count += 1
            else:
                # Track it; the real title might arrive in a few seconds.
                self._pending_new[hwnd] = now

        # 3) Watch baseline windows for title changes. If a pre-existing
        #    browser window's title just flipped to a DDC page, DDC put the
        #    promo into a NEW TAB inside that window. We can't close just
        #    the tab safely from outside, but we log a one-shot hint.
        for hwnd in list(self._baseline):
            if hwnd not in current:
                self._baseline.discard(hwnd)
                self._baseline_titles.pop(hwnd, None)
                continue
            title = _get_title(hwnd)
            prev = self._baseline_titles.get(hwnd, "")
            if title != prev:
                self._baseline_titles[hwnd] = title
                if (
                    _title_matches(title, self._keywords)
                    and not _title_matches(prev, self._keywords)
                ):
                    self._handle_baseline_hit(hwnd, title)

    def _handle_baseline_hit(self, hwnd: int, title: str) -> None:
        """
        DDC promo loaded as a new tab inside an already-open browser.
        Close just that tab by force-focusing the window and firing Ctrl+W.

        Users who don't want the ~150 ms focus flash can set
        QSFORGE_NO_CTRLW=1 and the module reverts to log-only behaviour.
        """
        # Debounce: if we already Ctrl+W-ed this hwnd in the last 2 seconds,
        # don't do it again. DDC opens two promo URLs in quick succession;
        # Chrome/Edge usually loads them into the same tab serially, so one
        # Ctrl+W is enough. A second keystroke would close a legitimate
        # user tab.
        now = time.monotonic()
        last = self._last_tab_close.get(hwnd, 0.0)
        if now - last < 2.0:
            return

        if not self._allow_ctrl_w:
            try:
                self.log(
                    "DDC promo tab detected in your existing browser window "
                    "(Ctrl+W injection disabled by QSFORGE_NO_CTRLW=1). "
                    "Close it manually or unset the env var."
                )
            except Exception:
                pass
            return

        if _close_active_tab_via_ctrl_w(hwnd):
            self._last_tab_close[hwnd] = now
            self._closed_count += 1
        else:
            try:
                self.log(
                    "DDC promo tab detected but Ctrl+W injection failed. "
                    "Close the datadrivenconstruction.io tab manually, or "
                    "run block_ddc_ads.bat once to permanently block it."
                )
            except Exception:
                pass


# ── CLI smoke test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Windows available:", _is_windows())
    if _is_windows():
        print(f"Currently {len(_list_top_windows())} top-level windows.")
        print("Watching for 20 s — try opening https://datadrivenconstruction.io/ …")
        with AdWindowWatcher(log=print, tail_seconds=20.0):
            time.sleep(0.1)
        time.sleep(21.0)
