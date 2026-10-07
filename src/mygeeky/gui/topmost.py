"""Keep a window genuinely on top on Windows.

Qt's WindowStaysOnTopHint sets WS_EX_TOPMOST once, but Windows doesn't keep
it: after clicking the taskbar, switching virtual desktops, waking from
sleep, or closing a full-screen app, the window can lose the flag, or another
always-on-top window (the taskbar, a call or video popup) ends up above it.
Then the folded icon disappears behind ordinary windows.

`keep_on_top(hwnd)` checks two things -- has it lost WS_EX_TOPMOST, and is
something else now drawn over its centre -- and only then lifts it back to the
top of the always-on-top band, without activating it (it never steals focus).
It stays put while a full-screen app is in front (a slideshow, a video, a
game), the way Windows' own notifications do.

Everything here is a no-op outside Windows.
"""

from __future__ import annotations

import sys

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x0008
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0001, 0x0002, 0x0010, 0x0200
GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

_user32 = None


def _api():
    global _user32
    if _user32 is None:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.WindowFromPoint.argtypes = [wintypes.POINT]
        u.WindowFromPoint.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        u.GetAncestor.restype = wintypes.HWND
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HMONITOR
        u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint]
        _user32 = u
    return _user32


def _rect(u, hwnd):
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _class(u, hwnd) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, 256)
    return buf.value


def fullscreen_app_in_front(u, own: int) -> bool:
    """Is the foreground window a full-screen app (not the desktop or us)?"""
    import ctypes
    from ctypes import wintypes
    fg = u.GetForegroundWindow()
    if not fg or int(fg) == own or _class(u, fg) in SHELL_CLASSES:
        return False

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not u.GetMonitorInfoW(u.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST), ctypes.byref(info)):
        return False
    m = info.rcMonitor
    left, top, right, bottom = _rect(u, fg)
    return left <= m.left and top <= m.top and right >= m.right and bottom >= m.bottom


def covered(u, own: int, ignore: set[int]) -> bool:
    """Is another top-level window drawn over the middle of ours?"""
    from ctypes import wintypes
    left, top, right, bottom = _rect(u, own)
    at = u.WindowFromPoint(wintypes.POINT((left + right) // 2, (top + bottom) // 2))
    root = u.GetAncestor(at, GA_ROOT) if at else None
    return bool(root) and int(root) != own and int(root) not in ignore


def keep_on_top(hwnd: int, ignore: set[int] | None = None) -> bool:
    """Re-assert always-on-top if Windows dropped it or something covers us.
    Returns True when it had to lift the window."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        u = _api()
        lost = not (u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
        if not (lost or covered(u, hwnd, ignore or set())):
            return False
        if fullscreen_app_in_front(u, hwnd):
            return False
        u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        return True
    except Exception:   # never let a z-order nicety break the panel
        return False
