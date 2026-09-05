"""Windows default audio playback device control via Core Audio COM.

Uses comtypes. Enumeration goes through the documented IMMDeviceEnumerator;
setting the default endpoint uses the undocumented-but-universal
IPolicyConfig interface (the same one every audio switcher on Windows uses).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import ClassVar

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

E_RENDER = 0
E_CAPTURE = 1

E_CONSOLE = 0
E_MULTIMEDIA = 1
E_COMMUNICATIONS = 2
ALL_ROLES = (E_CONSOLE, E_MULTIMEDIA, E_COMMUNICATIONS)

DEVICE_STATE_ACTIVE = 0x1
DEVICE_STATE_DISABLED = 0x2
DEVICE_STATE_NOTPRESENT = 0x4
DEVICE_STATE_UNPLUGGED = 0x8
DEVICE_STATEMASK_ALL = 0xF

STATE_NAMES = {
    DEVICE_STATE_ACTIVE: "active",
    DEVICE_STATE_DISABLED: "disabled",
    DEVICE_STATE_NOTPRESENT: "not_present",
    DEVICE_STATE_UNPLUGGED: "unplugged",
}

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
CLSID_PolicyConfigClient = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")

VT_LPWSTR = 31
STGM_READ = 0


# --------------------------------------------------------------------------- #
# COM interface definitions
# --------------------------------------------------------------------------- #


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


PKEY_Device_FriendlyName = PROPERTYKEY(
    GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14
)


class _PROPVARIANT_UNION(ctypes.Union):
    _fields_ = [
        ("pwszVal", wintypes.LPWSTR),
        ("ulVal", ctypes.c_ulong),
        ("_pad", ctypes.c_ubyte * 16),
    ]


class PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("u", _PROPVARIANT_UNION),
    ]


_ole32 = ctypes.WinDLL("ole32")
_ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
_ole32.PropVariantClear.restype = ctypes.c_long


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_: ClassVar[list] = [
        COMMETHOD(
            [], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.DWORD), "cProps")
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetAt",
            (["in"], wintypes.DWORD, "iProp"),
            (["out"], ctypes.POINTER(PROPERTYKEY), "pkey"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetValue",
            (["in"], ctypes.POINTER(PROPERTYKEY), "key"),
            (["out"], ctypes.POINTER(PROPVARIANT), "pv"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetValue",
            (["in"], ctypes.POINTER(PROPERTYKEY), "key"),
            (["in"], ctypes.POINTER(PROPVARIANT), "propvar"),
        ),
        COMMETHOD([], HRESULT, "Commit"),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-69A63C7256E3}")
    _methods_: ClassVar[list] = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], ctypes.POINTER(GUID), "iid"),
            (["in"], wintypes.DWORD, "dwClsCtx"),
            (["in"], ctypes.c_void_p, "pActivationParams"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IUnknown)), "ppInterface"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OpenPropertyStore",
            (["in"], wintypes.DWORD, "stgmAccess"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IPropertyStore)), "ppProperties"),
        ),
        COMMETHOD(
            [], HRESULT, "GetId", (["out"], ctypes.POINTER(wintypes.LPWSTR), "ppstrId")
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetState",
            (["out"], ctypes.POINTER(wintypes.DWORD), "pdwState"),
        ),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_: ClassVar[list] = [
        COMMETHOD(
            [],
            HRESULT,
            "GetCount",
            (["out"], ctypes.POINTER(wintypes.UINT), "pcDevices"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "Item",
            (["in"], wintypes.UINT, "nDevice"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "ppDevice"),
        ),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_: ClassVar[list] = [
        COMMETHOD(
            [],
            HRESULT,
            "EnumAudioEndpoints",
            (["in"], wintypes.DWORD, "dataFlow"),
            (["in"], wintypes.DWORD, "dwStateMask"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)), "ppDevices"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], wintypes.DWORD, "dataFlow"),
            (["in"], wintypes.DWORD, "role"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "ppEndpoint"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevice",
            (["in"], wintypes.LPCWSTR, "pwstrId"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "ppDevice"),
        ),
        # Register/UnregisterEndpointNotificationCallback omitted (not needed).
    ]


class IPolicyConfig(IUnknown):
    """Undocumented. Vtable layout is stable from Windows 7 through 11."""

    _iid_ = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
    _methods_: ClassVar[list] = [
        COMMETHOD(
            [],
            HRESULT,
            "GetMixFormat",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDeviceFormat",
            (["in"], wintypes.LPCWSTR),
            (["in"], wintypes.INT),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], wintypes.LPCWSTR)),
        COMMETHOD(
            [],
            HRESULT,
            "SetDeviceFormat",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetProcessingPeriod",
            (["in"], wintypes.LPCWSTR),
            (["in"], wintypes.INT),
            (["in"], ctypes.c_void_p),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetProcessingPeriod",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetShareMode",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetShareMode",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetPropertyValue",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetPropertyValue",
            (["in"], wintypes.LPCWSTR),
            (["in"], ctypes.c_void_p),
            (["in"], ctypes.c_void_p),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetDefaultEndpoint",
            (["in"], wintypes.LPCWSTR, "wszDeviceId"),
            (["in"], wintypes.DWORD, "eRole"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetEndpointVisibility",
            (["in"], wintypes.LPCWSTR),
            (["in"], wintypes.INT),
        ),
    ]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class AudioDevice:
    id: str
    name: str
    state: str
    is_default: bool = False

    @property
    def label(self) -> str:
        return self.name or self.id


# --------------------------------------------------------------------------- #
# High-level API
# --------------------------------------------------------------------------- #


def _enumerator() -> IMMDeviceEnumerator:
    comtypes.CoInitialize()
    return comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator,
        interface=IMMDeviceEnumerator,
        clsctx=comtypes.CLSCTX_ALL,
    )


def _friendly_name(dev: IMMDevice) -> str:
    try:
        store = dev.OpenPropertyStore(STGM_READ)
        pv = store.GetValue(PKEY_Device_FriendlyName)
    except comtypes.COMError:
        # Not-present devices may have no property store entry.
        return ""
    try:
        return pv.pwszVal if pv.vt == VT_LPWSTR and pv.pwszVal else ""
    finally:
        _ole32.PropVariantClear(ctypes.byref(pv))


def _default_id(enum: IMMDeviceEnumerator, flow: int, role: int) -> str | None:
    try:
        return enum.GetDefaultAudioEndpoint(flow, role).GetId()
    except comtypes.COMError:
        return None


def list_audio_devices(
    flow: int = E_RENDER, include_inactive: bool = False
) -> list[AudioDevice]:
    enum = _enumerator()
    mask = DEVICE_STATEMASK_ALL if include_inactive else DEVICE_STATE_ACTIVE
    coll = enum.EnumAudioEndpoints(flow, mask)
    default = _default_id(enum, flow, E_CONSOLE)
    out = []
    for i in range(coll.GetCount()):
        dev = coll.Item(i)
        dev_id = dev.GetId()
        out.append(
            AudioDevice(
                id=dev_id,
                name=_friendly_name(dev),
                state=STATE_NAMES.get(dev.GetState(), "unknown"),
                is_default=(dev_id == default),
            )
        )
    return out


def get_default_audio_device(
    flow: int = E_RENDER, role: int = E_CONSOLE
) -> AudioDevice | None:
    enum = _enumerator()
    try:
        dev = enum.GetDefaultAudioEndpoint(flow, role)
    except comtypes.COMError:
        return None
    return AudioDevice(
        id=dev.GetId(),
        name=_friendly_name(dev),
        state=STATE_NAMES.get(dev.GetState(), "unknown"),
        is_default=True,
    )


def set_default_audio_device(device_id: str, roles=ALL_ROLES) -> None:
    """Make ``device_id`` the default playback endpoint for the given roles."""
    comtypes.CoInitialize()
    policy = comtypes.CoCreateInstance(
        CLSID_PolicyConfigClient, interface=IPolicyConfig, clsctx=comtypes.CLSCTX_ALL
    )
    for role in roles:
        policy.SetDefaultEndpoint(device_id, role)
