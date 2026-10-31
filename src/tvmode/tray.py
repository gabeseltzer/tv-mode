"""Notification-area ("system tray") icon for ``tvmode watch``. Pure ctypes.

The icon lives on the listener's hidden window, so it shares its message
pump: nothing here creates threads. Other threads ask for a refresh with
``request_update()``, which only posts a message.

The icon is a small monitor drawn in code (no image files), coloured by the
current mode, so the mode is visible at a glance.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field

WM_APP = 0x8000
WM_TRAY_CALLBACK = WM_APP + 1  # mouse events on the icon
WM_TRAY_REFRESH = WM_APP + 2  # posted by request_update()
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4

MF_STRING = 0x0
MF_GRAYED = 0x1
MF_CHECKED = 0x8
MF_SEPARATOR = 0x800
TPM_RIGHTBUTTON = 0x2
TPM_NONOTIFY = 0x80
TPM_RETURNCMD = 0x100

ICON_SIZE = 32

# Mode colours (RGB). Modes not listed get a fallback; unknown is grey.
MODE_COLORS = {"game": (0x3B, 0x82, 0xF6), "tv": (0xF5, 0x9E, 0x0B)}
FALLBACK_COLORS = [(0x10, 0xB9, 0x81), (0xA8, 0x55, 0xF7), (0xEF, 0x44, 0x44)]
UNKNOWN_COLOR = (0x9C, 0xA3, 0xAF)


@dataclass
class MenuItem:
    label: str = ""  # empty label = separator
    command: str | None = None  # None = not clickable (a heading)
    checked: bool = False
    enabled: bool = True


SEPARATOR = MenuItem()


@dataclass
class TrayState:
    tooltip: str
    color: tuple[int, int, int]
    menu: list[MenuItem] = field(default_factory=list)


def mode_color(mode: str | None, all_modes: list[str]) -> tuple[int, int, int]:
    if mode is None:
        return UNKNOWN_COLOR
    if mode in MODE_COLORS:
        return MODE_COLORS[mode]
    others = [m for m in all_modes if m not in MODE_COLORS]
    i = others.index(mode) if mode in others else 0
    return FALLBACK_COLORS[i % len(FALLBACK_COLORS)]


def monitor_pixels(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Top-down BGRA pixels of a monitor: a coloured screen with a darker
    bezel, on a small stand. Everything else is transparent."""
    r, g, b = rgb
    dark = (r // 2, g // 2, b // 2)
    s = size / 32  # design grid is 32x32
    px = bytearray(size * size * 4)

    def fill(x0, y0, x1, y1, c):
        for y in range(int(y0 * s), int(y1 * s)):
            for x in range(int(x0 * s), int(x1 * s)):
                i = (y * size + x) * 4
                px[i : i + 4] = bytes((c[2], c[1], c[0], 255))

    fill(1, 3, 31, 24, dark)  # bezel
    fill(3, 5, 29, 22, (r, g, b))  # screen
    fill(13, 24, 19, 27, dark)  # neck
    fill(8, 27, 24, 30, dark)  # foot
    return bytes(px)


# --------------------------------------------------------------------------- #
# Win32
# --------------------------------------------------------------------------- #


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


_dlls = None


def _win():
    global _dlls
    if _dlls is not None:
        return _dlls
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    sh = ctypes.WinDLL("shell32", use_last_error=True)
    sh.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    sh.Shell_NotifyIconW.restype = wintypes.BOOL
    g.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.CreateBitmap.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    g.CreateBitmap.restype = wintypes.HBITMAP
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    u.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
    u.CreateIconIndirect.restype = wintypes.HICON
    u.DestroyIcon.argtypes = [wintypes.HICON]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_size_t,
        wintypes.LPCWSTR,
    ]
    u.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    u.TrackPopupMenu.restype = wintypes.BOOL
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.RegisterWindowMessageW.restype = wintypes.UINT
    _dlls = (u, g, sh)
    return _dlls


def make_icon(rgb: tuple[int, int, int], size: int = ICON_SIZE) -> int:
    """Build an HICON of the monitor glyph. Caller destroys it."""
    u, g, _ = _win()
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = size
    bih.biHeight = -size  # top-down
    bih.biPlanes = 1
    bih.biBitCount = 32
    bits = ctypes.c_void_p()
    color = g.CreateDIBSection(None, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
    if not color:
        raise ctypes.WinError(ctypes.get_last_error())
    data = monitor_pixels(size, rgb)
    ctypes.memmove(bits, data, len(data))
    mask = g.CreateBitmap(size, size, 1, 1, None)  # alpha channel does the work
    try:
        info = ICONINFO(True, 0, 0, mask, color)
        hicon = u.CreateIconIndirect(ctypes.byref(info))
        if not hicon:
            raise ctypes.WinError(ctypes.get_last_error())
        return hicon
    finally:
        g.DeleteObject(mask)
        g.DeleteObject(color)


class Tray:
    """Owns one notification-area icon on ``hwnd``.

    ``state()`` is called (on the pump thread) whenever the icon is refreshed
    or its menu opened; ``on_command(command)`` gets the chosen menu item."""

    def __init__(
        self,
        state: Callable[[], TrayState],
        on_command: Callable[[str], None],
    ) -> None:
        self._state = state
        self._on_command = on_command
        self._hwnd: int | None = None
        self._hicon: int | None = None
        self._color: tuple[int, int, int] | None = None
        self._taskbar_created = 0

    def attach(self, hwnd: int) -> None:
        u, _, _ = _win()
        self._hwnd = hwnd
        # Explorer broadcasts this after it restarts; the icon must be re-added.
        self._taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
        self._add()

    def request_update(self) -> None:
        """Thread-safe: ask the pump thread to refresh icon and tooltip."""
        if self._hwnd:
            _win()[0].PostMessageW(self._hwnd, WM_TRAY_REFRESH, 0, 0)

    def handle(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int | None:
        """Window-procedure hook. Returns a result if the message was ours."""
        if msg == WM_TRAY_CALLBACK:
            if (lparam & 0xFFFF) in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            return 0
        if msg == WM_TRAY_REFRESH:
            self._notify(NIM_MODIFY)
            return 0
        if self._taskbar_created and msg == self._taskbar_created:
            self._color = None
            self._add()
            return 0
        if msg == WM_DESTROY:
            self.remove()
        return None

    def remove(self) -> None:
        if self._hwnd is None:
            return
        _, _, sh = _win()
        nid = self._nid()
        sh.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        if self._hicon:
            _win()[0].DestroyIcon(self._hicon)
            self._hicon = None
        self._hwnd = None

    # -- internals -------------------------------------------------------- #
    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        return nid

    def _add(self) -> None:
        if not self._notify(NIM_ADD):
            raise ctypes.WinError(ctypes.get_last_error(), "Shell_NotifyIconW(add)")

    def _notify(self, action: int) -> bool:
        if self._hwnd is None:
            return False
        u, _, sh = _win()
        st = self._state()
        if st.color != self._color or not self._hicon:
            old = self._hicon
            self._hicon = make_icon(st.color)
            self._color = st.color
            if old:
                u.DestroyIcon(old)
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY_CALLBACK
        nid.hIcon = self._hicon
        nid.szTip = st.tooltip[:127]
        return bool(sh.Shell_NotifyIconW(action, ctypes.byref(nid)))

    def _show_menu(self) -> None:
        u, _, _ = _win()
        items = self._state().menu
        menu = u.CreatePopupMenu()
        commands: dict[int, str] = {}
        try:
            for i, item in enumerate(items, start=1):
                if not item.label:
                    u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING
                if item.checked:
                    flags |= MF_CHECKED
                if not item.enabled or item.command is None:
                    flags |= MF_GRAYED
                u.AppendMenuW(menu, flags, i, item.label)
                if item.command:
                    commands[i] = item.command
            pt = wintypes.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            # Without this the menu doesn't close when you click elsewhere.
            u.SetForegroundWindow(self._hwnd)
            chosen = u.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x,
                pt.y,
                0,
                self._hwnd,
                None,
            )
            u.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            u.DestroyMenu(menu)
        if chosen in commands:
            self._on_command(commands[chosen])
