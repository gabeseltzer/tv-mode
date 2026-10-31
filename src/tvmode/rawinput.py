"""Per-device keyboard and mouse events via the Windows Raw Input API.

This is the only Windows API that says *which* keyboard or mouse produced an
event; low-level hooks do not carry the device handle. Pure ctypes.

Usage::

    def on_event(ev: InputEvent) -> None: ...
    listener = RawInputListener(on_event, on_devices_changed=refresh)
    listener.run()          # blocks, pumping messages; listener.stop() from
                            # another thread ends it

Gotcha: a message-only window (``HWND_MESSAGE`` parent) never receives
background raw input, so a real hidden top-level window is created instead.
"""

from __future__ import annotations

import ctypes
import re
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2

RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000

RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007

RI_KEY_BREAK = 0x01
MOUSE_MOVE_ABSOLUTE = 0x01

HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
HID_USAGE_GENERIC_KEYBOARD = 0x06

WM_INPUT = 0x00FF
WM_INPUT_DEVICE_CHANGE = 0x00FE
WM_CLOSE = 0x0010
WM_DISPLAYCHANGE = 0x007E
WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007
WM_TIMER = 0x0113
WM_DESTROY = 0x0002

WS_OVERLAPPED = 0x00000000

TIMER_SETTLE = 1  # one-shot, restarted by each display change
TIMER_POLL = 2  # periodic

ERROR_CLASS_ALREADY_EXISTS = 1410
INVALID = 0xFFFFFFFF

KINDS = {RIM_TYPEMOUSE: "mouse", RIM_TYPEKEYBOARD: "keyboard", RIM_TYPEHID: "hid"}

# --------------------------------------------------------------------------- #
# Structures (layouts match 64-bit Windows headers; ctypes handles padding)
# --------------------------------------------------------------------------- #

if sys.platform == "win32":
    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
else:  # pragma: no cover - lets the module import on other platforms
    WNDPROC = ctypes.CFUNCTYPE(ctypes.c_ssize_t)


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class _MOUSEBUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT)]


class _MOUSEBUTTONUNION(ctypes.Union):
    _anonymous_ = ("s",)
    _fields_ = [("ulButtons", wintypes.ULONG), ("s", _MOUSEBUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("u", _MOUSEBUTTONUNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWHID(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wintypes.DWORD),
        ("dwCount", wintypes.DWORD),
        ("bRawData", wintypes.BYTE * 1),
    ]


class _RAWINPUTDATA(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD), ("hid", RAWHID)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", _RAWINPUTDATA)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InputDevice:
    handle: int
    kind: str  # "keyboard" | "mouse" | "hid"
    path: str  # e.g. \\?\HID#VID_046D&PID_C52B&MI_00#7&...#{guid}
    description: str = ""  # from the registry when available

    @property
    def vid_pid(self) -> str:
        m = re.search(r"VID_([0-9A-Fa-f]{4}).*?PID_([0-9A-Fa-f]{4})", self.path)
        return f"VID_{m.group(1).upper()}&PID_{m.group(2).upper()}" if m else ""

    @property
    def label(self) -> str:
        return self.description or self.vid_pid or self.path

    def match_keys(self) -> tuple[str, ...]:
        """Strings a config matcher is compared against."""
        return (self.description, self.vid_pid, self.path)


@dataclass(frozen=True)
class InputEvent:
    kind: str  # "keyboard" | "mouse"
    handle: int
    dx: int = 0  # relative mouse motion (counts)
    dy: int = 0
    key_down: bool = False  # keyboard: a make (press), not a break (release)


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #

_user32_cache = None


def _user32():
    global _user32_cache
    if _user32_cache is not None:
        return _user32_cache
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetRawInputDeviceList.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICELIST),
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    u.GetRawInputDeviceList.restype = wintypes.UINT
    u.GetRawInputDeviceInfoW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.UINT),
    ]
    u.GetRawInputDeviceInfoW.restype = wintypes.UINT
    u.RegisterRawInputDevices.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICE),
        wintypes.UINT,
        wintypes.UINT,
    ]
    u.RegisterRawInputDevices.restype = wintypes.BOOL
    u.GetRawInputData.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    u.GetRawInputData.restype = wintypes.UINT
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.RegisterClassW.restype = wintypes.ATOM
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    u.PostQuitMessage.argtypes = [ctypes.c_int]
    u.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.restype = ctypes.c_ssize_t
    u.SetTimer.argtypes = [
        wintypes.HWND,
        ctypes.c_size_t,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    u.SetTimer.restype = ctypes.c_size_t
    u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    u.KillTimer.restype = wintypes.BOOL
    _user32_cache = u
    return u


def _winerr(what: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(f"{what} failed: {ctypes.FormatError(code)} ({code})")


def _device_path(handle: int) -> str:
    u = _user32()
    size = wintypes.UINT(0)
    u.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
    if size.value == 0:
        return ""
    buf = ctypes.create_unicode_buffer(size.value + 1)
    n = u.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size))
    if n == INVALID:
        return ""
    return buf.value


def registry_key_for(path: str) -> str | None:
    r"""Map a raw input path ``\\?\HID#VID_X&PID_Y#inst#{guid}`` to its
    ``SYSTEM\CurrentControlSet\Enum\HID\VID_X&PID_Y\inst`` registry key."""
    m = re.match(r"\\\\\?\\([^#]+)#([^#]+)#([^#]+)#\{", path)
    if not m:
        return None
    return rf"SYSTEM\CurrentControlSet\Enum\{m.group(1)}\{m.group(2)}\{m.group(3)}"


def clean_device_desc(value: str) -> str:
    """``@input.inf,%hid_device%;HID Keyboard Device`` -> ``HID Keyboard Device``."""
    return value.rsplit(";", 1)[-1].strip()


def registry_description(path: str) -> str:
    """Best-effort friendly name for a raw input device path."""
    key = registry_key_for(path)
    if key is None:
        return ""
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            for name in ("FriendlyName", "DeviceDesc"):
                try:
                    v, _ = winreg.QueryValueEx(k, name)
                except FileNotFoundError:
                    continue
                if isinstance(v, str) and v:
                    return clean_device_desc(v)
    except OSError:
        pass
    return ""


def list_input_devices() -> list[InputDevice]:
    """Enumerate attached raw input devices (keyboards, mice, other HID)."""
    u = _user32()
    count = wintypes.UINT(0)
    sz = ctypes.sizeof(RAWINPUTDEVICELIST)
    if u.GetRawInputDeviceList(None, ctypes.byref(count), sz) == INVALID:
        raise _winerr("GetRawInputDeviceList(count)")
    if count.value == 0:
        return []
    arr = (RAWINPUTDEVICELIST * count.value)()
    n = u.GetRawInputDeviceList(arr, ctypes.byref(count), sz)
    if n == INVALID:
        raise _winerr("GetRawInputDeviceList")
    out: list[InputDevice] = []
    for i in range(n):
        handle = arr[i].hDevice or 0
        path = _device_path(handle)
        out.append(
            InputDevice(
                handle=handle,
                kind=KINDS.get(arr[i].dwType, "hid"),
                path=path,
                description=registry_description(path),
            )
        )
    return out


def parse_raw_input(raw: RAWINPUT) -> InputEvent | None:
    """Turn a RAWINPUT block into an ``InputEvent`` (None for HID/absolute)."""
    handle = raw.header.hDevice or 0
    if raw.header.dwType == RIM_TYPEKEYBOARD:
        kb = raw.data.keyboard
        return InputEvent(
            kind="keyboard", handle=handle, key_down=not (kb.Flags & RI_KEY_BREAK)
        )
    if raw.header.dwType == RIM_TYPEMOUSE:
        m = raw.data.mouse
        if m.usFlags & MOUSE_MOVE_ABSOLUTE:
            return None  # tablets / RDP; no relative motion to reason about
        return InputEvent(kind="mouse", handle=handle, dx=m.lLastX, dy=m.lLastY)
    return None


# --------------------------------------------------------------------------- #
# Listener
# --------------------------------------------------------------------------- #

_CLASS_NAME = "tvmode.rawinput"


class RawInputListener:
    """Hidden window that receives raw keyboard/mouse input in the background
    and hands each event to ``on_event``. ``on_devices_changed`` (optional) is
    called when a device arrives or is removed.

    ``on_state_check`` (optional) is called ``display_settle`` seconds after
    the display configuration or the set of attached hardware changes (a
    monitor plugged in, a TV turned on; debounced, so a burst of changes gives
    one call) and every ``poll_interval`` seconds, so the owner can re-read
    state that something else may have changed behind its back.

    ``on_window(hwnd)`` is called once the hidden window exists, and
    ``on_message(hwnd, msg, wparam, lparam)`` sees every message first and
    may return a result to claim it (used by the tray icon).

    Exceptions raised by the callbacks are passed to ``on_error`` (default:
    ignored) so they can never kill the message pump."""

    def __init__(
        self,
        on_event: Callable[[InputEvent], None],
        on_devices_changed: Callable[[], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_state_check: Callable[[], None] | None = None,
        display_settle: float = 1.0,
        poll_interval: float | None = 15.0,
        on_window: Callable[[int], None] | None = None,
        on_message: Callable[[int, int, int, int], int | None] | None = None,
    ) -> None:
        self._on_window = on_window
        self._on_message = on_message
        self._on_event = on_event
        self._on_devices_changed = on_devices_changed
        self._on_state_check = on_state_check
        self._display_settle_ms = max(int(display_settle * 1000), 10)
        self._poll_ms = int(poll_interval * 1000) if poll_interval else 0
        self._on_error = on_error
        self._hwnd: int | None = None
        self._buf = ctypes.create_string_buffer(max(ctypes.sizeof(RAWINPUT), 64))
        # keep a reference so the callback is not garbage collected
        self._wndproc = WNDPROC(self._proc)

    def _guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except BaseException as e:  # noqa: BLE001 - never kill the pump
            if self._on_error is not None:
                self._on_error(e)

    # -- window procedure ------------------------------------------------- #
    def _proc(self, hwnd, msg, wparam, lparam):
        u = _user32()
        if self._on_message is not None:
            try:
                r = self._on_message(hwnd, msg, wparam, lparam)
            except BaseException as e:  # noqa: BLE001 - never kill the pump
                r = None
                if self._on_error is not None:
                    self._on_error(e)
            if r is not None:
                return r
        if msg == WM_INPUT:
            self._handle_input(lparam)
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)  # required
        if msg == WM_INPUT_DEVICE_CHANGE:
            if self._on_devices_changed is not None:
                self._guard(self._on_devices_changed)
            return 0
        if msg == WM_DISPLAYCHANGE or (
            msg == WM_DEVICECHANGE and wparam == DBT_DEVNODES_CHANGED
        ):
            if self._on_state_check is not None:
                # Restarting the timer debounces the burst a switch produces.
                u.SetTimer(hwnd, TIMER_SETTLE, self._display_settle_ms, None)
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_TIMER and wparam in (TIMER_SETTLE, TIMER_POLL):
            if wparam == TIMER_SETTLE:
                u.KillTimer(hwnd, TIMER_SETTLE)
            if self._on_state_check is not None:
                self._guard(self._on_state_check)
            return 0
        if msg == WM_CLOSE:
            u.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle_input(self, lparam) -> None:
        u = _user32()
        size = wintypes.UINT(0)
        hdr = ctypes.sizeof(RAWINPUTHEADER)
        u.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), hdr)
        if size.value == 0:
            return
        if size.value > len(self._buf):
            self._buf = ctypes.create_string_buffer(size.value)
        n = u.GetRawInputData(lparam, RID_INPUT, self._buf, ctypes.byref(size), hdr)
        if n == INVALID or n < hdr:
            return
        raw = RAWINPUT.from_buffer(self._buf)
        ev = parse_raw_input(raw)
        if ev is None or ev.handle == 0:  # 0 = injected input (SendInput/RDP)
            return
        self._guard(self._on_event, ev)

    # -- lifecycle -------------------------------------------------------- #
    def _create_window(self) -> int:
        u = _user32()
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = _CLASS_NAME
        registered = u.RegisterClassW(ctypes.byref(wc))
        if not registered and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
            raise _winerr("RegisterClassW")
        # A real (hidden) top-level window, *not* HWND_MESSAGE: message-only
        # windows do not receive RIDEV_INPUTSINK input.
        hwnd = u.CreateWindowExW(
            0, _CLASS_NAME, "tvmode", WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None
        )
        if not hwnd:
            raise _winerr("CreateWindowExW")
        return hwnd

    def _register(self, hwnd: int) -> None:
        flags = RIDEV_INPUTSINK | RIDEV_DEVNOTIFY
        devs = (RAWINPUTDEVICE * 2)(
            RAWINPUTDEVICE(
                HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_KEYBOARD, flags, hwnd
            ),
            RAWINPUTDEVICE(
                HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_MOUSE, flags, hwnd
            ),
        )
        ok = _user32().RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE))
        if not ok:
            raise _winerr("RegisterRawInputDevices")

    def run(self) -> None:
        """Create the window, register for input and pump messages until
        ``stop()`` is called. Must run on the thread that created it."""
        u = _user32()
        self._hwnd = self._create_window()
        try:
            self._register(self._hwnd)
            if self._on_state_check is not None and self._poll_ms:
                u.SetTimer(self._hwnd, TIMER_POLL, self._poll_ms, None)
            if self._on_window is not None:
                self._on_window(self._hwnd)
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._hwnd = None

    def stop(self) -> None:
        """Ask the message loop to exit. Safe to call from another thread."""
        if self._hwnd:
            _user32().PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
