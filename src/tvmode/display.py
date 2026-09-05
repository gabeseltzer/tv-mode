"""Windows display topology control via the DisplayConfig (CCD) API.

Pure ctypes; no third-party dependencies. Two layers:

* Low-level: structure definitions and thin wrappers around
  QueryDisplayConfig / SetDisplayConfig / DisplayConfigGetDeviceInfo.
* High-level: ``list_displays()`` and ``set_active_displays()`` which reason in
  terms of *targets* (physical monitors) identified by a stable device path.

The path-selection logic (``plan_paths``) is pure Python over plain data so it
can be unit tested without touching the OS.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

QDC_ALL_PATHS = 0x1
QDC_ONLY_ACTIVE_PATHS = 0x2
QDC_DATABASE_CURRENT = 0x4

SDC_TOPOLOGY_SUPPLIED = 0x10
SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x20
SDC_VALIDATE = 0x40
SDC_APPLY = 0x80
SDC_NO_OPTIMIZATION = 0x100
SDC_SAVE_TO_DATABASE = 0x200
SDC_ALLOW_CHANGES = 0x400
SDC_PATH_PERSIST_IF_REQUIRED = 0x800
SDC_ALLOW_PATH_ORDER_CHANGES = 0x2000
SDC_VIRTUAL_MODE_AWARE = 0x8000

DISPLAYCONFIG_PATH_ACTIVE = 0x1
DISPLAYCONFIG_PATH_MODE_IDX_INVALID = 0xFFFFFFFF

DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2

ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122

_WIN32_ERRORS = {
    5: "ERROR_ACCESS_DENIED",
    31: "ERROR_GEN_FAILURE",
    50: "ERROR_NOT_SUPPORTED",
    87: "ERROR_INVALID_PARAMETER",
    1610: "ERROR_BAD_CONFIGURATION",
}

OUTPUT_TECHNOLOGY = {
    0xFFFFFFFF: "other",
    0: "vga",
    1: "svideo",
    2: "composite",
    3: "component",
    4: "dvi",
    5: "hdmi",
    6: "lvds",
    8: "d_jpn",
    9: "sdi",
    10: "displayport",
    11: "displayport_embedded",
    12: "udi",
    13: "udi_embedded",
    14: "sdtv_dongle",
    15: "miracast",
    16: "indirect_wired",
    17: "indirect_virtual",
    0x80000000: "internal",
}


# --------------------------------------------------------------------------- #
# Structures
# --------------------------------------------------------------------------- #


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    def as_int(self) -> int:
        return (self.HighPart << 32) | self.LowPart


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class DISPLAYCONFIG_2DREGION(ctypes.Structure):
    _fields_ = [("cx", wintypes.UINT), ("cy", wintypes.UINT)]


class DISPLAYCONFIG_VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [
        ("pixelRate", ctypes.c_uint64),
        ("hSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("vSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("activeSize", DISPLAYCONFIG_2DREGION),
        ("totalSize", DISPLAYCONFIG_2DREGION),
        ("videoStandard", wintypes.UINT),
        ("scanLineOrdering", wintypes.UINT),
    ]


class DISPLAYCONFIG_TARGET_MODE(ctypes.Structure):
    _fields_ = [("targetVideoSignalInfo", DISPLAYCONFIG_VIDEO_SIGNAL_INFO)]


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECTL(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class DISPLAYCONFIG_SOURCE_MODE(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("pixelFormat", wintypes.UINT),
        ("position", POINTL),
    ]


class DISPLAYCONFIG_DESKTOP_IMAGE_INFO(ctypes.Structure):
    _fields_ = [
        ("PathSourceSize", POINTL),
        ("DesktopImageRegion", RECTL),
        ("DesktopImageClip", RECTL),
    ]


class _MODE_UNION(ctypes.Union):
    _fields_ = [
        ("targetMode", DISPLAYCONFIG_TARGET_MODE),
        ("sourceMode", DISPLAYCONFIG_SOURCE_MODE),
        ("desktopImageInfo", DISPLAYCONFIG_DESKTOP_IMAGE_INFO),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", LUID),
        ("u", _MODE_UNION),
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", LUID),
        ("id", wintypes.UINT),
    ]


class DISPLAYCONFIG_TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("flags", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("edidManufactureId", wintypes.USHORT),
        ("edidProductCodeId", wintypes.USHORT),
        ("connectorInstance", wintypes.UINT),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * 32),
    ]


# Sanity-check struct sizes against the documented Win32 layout.
assert ctypes.sizeof(DISPLAYCONFIG_PATH_INFO) == 72, ctypes.sizeof(DISPLAYCONFIG_PATH_INFO)
assert ctypes.sizeof(DISPLAYCONFIG_MODE_INFO) == 64, ctypes.sizeof(DISPLAYCONFIG_MODE_INFO)
assert ctypes.sizeof(DISPLAYCONFIG_TARGET_DEVICE_NAME) == 420


# --------------------------------------------------------------------------- #
# Low-level wrappers
# --------------------------------------------------------------------------- #


class DisplayConfigError(RuntimeError):
    def __init__(self, func: str, code: int):
        name = _WIN32_ERRORS.get(code, "")
        super().__init__(f"{func} failed with error {code} {name}".rstrip())
        self.func = func
        self.code = code


_user32_cache = None


def _user32():
    global _user32_cache
    if _user32_cache is not None:
        return _user32_cache
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetDisplayConfigBufferSizes.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    ]
    u.GetDisplayConfigBufferSizes.restype = wintypes.LONG
    u.QueryDisplayConfig.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
        ctypes.c_void_p,
    ]
    u.QueryDisplayConfig.restype = wintypes.LONG
    u.SetDisplayConfig.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        wintypes.UINT,
        ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
        wintypes.UINT,
    ]
    u.SetDisplayConfig.restype = wintypes.LONG
    u.DisplayConfigGetDeviceInfo.argtypes = [ctypes.POINTER(DISPLAYCONFIG_DEVICE_INFO_HEADER)]
    u.DisplayConfigGetDeviceInfo.restype = wintypes.LONG
    _user32_cache = u
    return u


def query_display_config(flags: int = QDC_ALL_PATHS):
    """Return (paths, modes) as ctypes arrays for the given QDC flags."""
    u = _user32()
    n_paths = wintypes.UINT()
    n_modes = wintypes.UINT()
    # Buffer sizes can change between the two calls if a monitor is plugged
    # in; retry on ERROR_INSUFFICIENT_BUFFER.
    for _ in range(5):
        rc = u.GetDisplayConfigBufferSizes(flags, ctypes.byref(n_paths), ctypes.byref(n_modes))
        if rc != ERROR_SUCCESS:
            raise DisplayConfigError("GetDisplayConfigBufferSizes", rc)
        paths = (DISPLAYCONFIG_PATH_INFO * n_paths.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * n_modes.value)()
        rc = u.QueryDisplayConfig(
            flags, ctypes.byref(n_paths), paths, ctypes.byref(n_modes), modes, None
        )
        if rc == ERROR_INSUFFICIENT_BUFFER:
            continue
        if rc != ERROR_SUCCESS:
            raise DisplayConfigError("QueryDisplayConfig", rc)
        return paths[: n_paths.value], modes[: n_modes.value]
    raise DisplayConfigError("QueryDisplayConfig", ERROR_INSUFFICIENT_BUFFER)


def get_target_name(adapter: LUID, target_id: int) -> DISPLAYCONFIG_TARGET_DEVICE_NAME:
    u = _user32()
    info = DISPLAYCONFIG_TARGET_DEVICE_NAME()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = adapter
    info.header.id = target_id
    rc = u.DisplayConfigGetDeviceInfo(ctypes.byref(info.header))
    if rc != ERROR_SUCCESS:
        raise DisplayConfigError("DisplayConfigGetDeviceInfo(target)", rc)
    return info


def get_source_name(adapter: LUID, source_id: int) -> str:
    u = _user32()
    info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = adapter
    info.header.id = source_id
    rc = u.DisplayConfigGetDeviceInfo(ctypes.byref(info.header))
    if rc != ERROR_SUCCESS:
        raise DisplayConfigError("DisplayConfigGetDeviceInfo(source)", rc)
    return info.viewGdiDeviceName


# --------------------------------------------------------------------------- #
# Plain-data model (testable without Windows)
# --------------------------------------------------------------------------- #

TargetKey = tuple[int, int]  # (adapter LUID as int, target id)
SourceKey = tuple[int, int]  # (adapter LUID as int, source id)


@dataclass(frozen=True)
class PathRecord:
    """A plain-data view of one DISPLAYCONFIG_PATH_INFO entry."""

    index: int
    source: SourceKey
    target: TargetKey
    active: bool
    available: bool


@dataclass
class DisplayInfo:
    """One physical monitor (a *target* in CCD terminology)."""

    target: TargetKey
    friendly_name: str
    device_path: str
    output: str
    active: bool
    available: bool
    gdi_name: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.friendly_name or self.device_path or f"target {self.target[1]}"


def _path_records(paths) -> list[PathRecord]:
    out = []
    for i, p in enumerate(paths):
        out.append(
            PathRecord(
                index=i,
                source=(p.sourceInfo.adapterId.as_int(), p.sourceInfo.id),
                target=(p.targetInfo.adapterId.as_int(), p.targetInfo.id),
                active=bool(p.flags & DISPLAYCONFIG_PATH_ACTIVE),
                available=bool(p.targetInfo.targetAvailable),
            )
        )
    return out


class PlanError(ValueError):
    pass


def plan_paths(records: list[PathRecord], wanted: set[TargetKey]) -> set[int]:
    """Choose which path indices should be ACTIVE so that exactly ``wanted``
    targets are driven, each by a distinct source (extended desktop).

    Preference order for each wanted target:
      1. A path that is currently active (keeps its existing source).
      2. A path whose source is not yet claimed by another wanted target.

    Raises ``PlanError`` if a wanted target has no available path or if the
    sources cannot be assigned distinctly.
    """
    if not wanted:
        raise PlanError("refusing to plan a topology with zero active displays")

    by_target: dict[TargetKey, list[PathRecord]] = {}
    for r in records:
        by_target.setdefault(r.target, []).append(r)

    missing = [t for t in wanted if t not in by_target]
    if missing:
        raise PlanError(f"no display paths exist for targets {missing}")

    unavailable = [t for t in wanted if not any(r.available for r in by_target[t])]
    if unavailable:
        raise PlanError(f"targets not connected/available: {unavailable}")

    chosen: dict[TargetKey, PathRecord] = {}
    used_sources: set[SourceKey] = set()

    # Pass 1: keep currently active paths for wanted targets.
    for t in sorted(wanted):
        for r in by_target[t]:
            if r.active and r.source not in used_sources:
                chosen[t] = r
                used_sources.add(r.source)
                break

    # Pass 2: assign the remaining wanted targets to free sources.
    for t in sorted(wanted):
        if t in chosen:
            continue
        for r in sorted(by_target[t], key=lambda r: r.source):
            if r.source not in used_sources:
                chosen[t] = r
                used_sources.add(r.source)
                break
        else:
            raise PlanError(f"could not find a free source for target {t}")

    return {r.index for r in chosen.values()}


# --------------------------------------------------------------------------- #
# High-level API
# --------------------------------------------------------------------------- #


def list_displays(include_phantom: bool = False) -> list[DisplayInfo]:
    """Enumerate every known monitor target with its current state.

    The CCD API also returns phantom targets for every unused connector; those
    are dropped unless ``include_phantom`` is set.
    """
    paths, _modes = query_display_config(QDC_ALL_PATHS)
    seen: dict[TargetKey, DisplayInfo] = {}
    for p in paths:
        key = (p.targetInfo.adapterId.as_int(), p.targetInfo.id)
        active = bool(p.flags & DISPLAYCONFIG_PATH_ACTIVE)
        if key in seen:
            if active:
                seen[key].active = True
                try:
                    seen[key].gdi_name = get_source_name(p.sourceInfo.adapterId, p.sourceInfo.id)
                except DisplayConfigError:
                    pass
            continue
        try:
            name = get_target_name(p.targetInfo.adapterId, p.targetInfo.id)
            friendly = name.monitorFriendlyDeviceName
            dev_path = name.monitorDevicePath
            extra = {
                "edid_manufacturer": name.edidManufactureId,
                "edid_product": name.edidProductCodeId,
                "connector_instance": name.connectorInstance,
            }
        except DisplayConfigError:
            friendly, dev_path, extra = "", "", {}
        gdi = ""
        if active:
            try:
                gdi = get_source_name(p.sourceInfo.adapterId, p.sourceInfo.id)
            except DisplayConfigError:
                pass
        seen[key] = DisplayInfo(
            target=key,
            friendly_name=friendly,
            device_path=dev_path,
            output=OUTPUT_TECHNOLOGY.get(
                p.targetInfo.outputTechnology, hex(p.targetInfo.outputTechnology)
            ),
            active=active,
            available=bool(p.targetInfo.targetAvailable),
            gdi_name=gdi,
            extra=extra,
        )
    if include_phantom:
        return list(seen.values())
    return [d for d in seen.values() if d.available or d.active]


def active_targets() -> set[TargetKey]:
    paths, _ = query_display_config(QDC_ONLY_ACTIVE_PATHS)
    return {(p.targetInfo.adapterId.as_int(), p.targetInfo.id) for p in paths}


def set_active_displays(wanted: set[TargetKey], *, validate_only: bool = False) -> None:
    """Make exactly ``wanted`` targets active (extended), everything else off.

    Uses SDC_TOPOLOGY_SUPPLIED so Windows fills in modes and positions from
    its own database (or picks sensible defaults for a first-time layout).
    """
    paths, _modes = query_display_config(QDC_ALL_PATHS)
    records = _path_records(paths)
    active_idx = plan_paths(records, wanted)

    arr = (DISPLAYCONFIG_PATH_INFO * len(paths))(*paths)
    for i in range(len(arr)):
        if i in active_idx:
            arr[i].flags |= DISPLAYCONFIG_PATH_ACTIVE
        else:
            arr[i].flags &= ~DISPLAYCONFIG_PATH_ACTIVE & 0xFFFFFFFF
        # Let Windows choose modes.
        arr[i].sourceInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID
        arr[i].targetInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID

    u = _user32()
    # NB: SDC_VIRTUAL_MODE_AWARE makes this call fail with ERROR_INVALID_PARAMETER.
    base = SDC_TOPOLOGY_SUPPLIED | SDC_ALLOW_PATH_ORDER_CHANGES
    rc = u.SetDisplayConfig(len(arr), arr, 0, None, base | SDC_VALIDATE)
    if rc != ERROR_SUCCESS:
        raise DisplayConfigError("SetDisplayConfig(validate)", rc)
    if validate_only:
        return
    rc = u.SetDisplayConfig(len(arr), arr, 0, None, base | SDC_APPLY | SDC_SAVE_TO_DATABASE)
    if rc != ERROR_SUCCESS:
        raise DisplayConfigError("SetDisplayConfig(apply)", rc)
