"""Windows default audio playback device control via Core Audio COM.

Uses pycaw (comtypes-based) for the interface definitions and constants.
Enumeration goes through the documented IMMDeviceEnumerator; setting the
default endpoint uses the undocumented-but-universal IPolicyConfig interface
(the same one every audio switcher on Windows uses).
"""

from __future__ import annotations

from dataclasses import dataclass

import comtypes
from comtypes import GUID
from pycaw.api.mmdeviceapi import IMMDevice, IMMDeviceEnumerator
from pycaw.api.mmdeviceapi.depend import PROPERTYKEY
from pycaw.api.mmdeviceapi.depend.structures import VT_LPWSTR
from pycaw.constants import (
    DEVICE_STATE,
    STGM,
    AudioDeviceState,
    CLSID_MMDeviceEnumerator,
    EDataFlow,
    ERole,
)
from pycaw.utils import AudioUtilities

ALL_ROLES = (ERole.eConsole, ERole.eMultimedia, ERole.eCommunications)

PKEY_Device_FriendlyName = PROPERTYKEY()
PKEY_Device_FriendlyName.fmtid = GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}")
PKEY_Device_FriendlyName.pid = 14


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
        store = dev.OpenPropertyStore(STGM.STGM_READ.value)
        pv = store.GetValue(PKEY_Device_FriendlyName)
    except comtypes.COMError:
        # Not-present devices may have no property store entry.
        return ""
    try:
        return pv.GetValue() or "" if pv.vt == VT_LPWSTR else ""
    finally:
        pv.clear()


def _state_name(raw: int) -> str:
    try:
        return AudioDeviceState(raw).name
    except ValueError:
        return f"unknown({raw:#x})"


def _default_id(enum: IMMDeviceEnumerator, flow: int, role: int) -> str | None:
    try:
        return enum.GetDefaultAudioEndpoint(flow, role).GetId()
    except comtypes.COMError:
        return None


def _to_device(dev: IMMDevice, default_id: str | None) -> AudioDevice:
    dev_id = dev.GetId()
    return AudioDevice(
        id=dev_id,
        name=_friendly_name(dev),
        state=_state_name(dev.GetState()),
        is_default=(dev_id == default_id),
    )


def list_audio_devices(
    flow: int = EDataFlow.eRender.value, include_inactive: bool = False
) -> list[AudioDevice]:
    enum = _enumerator()
    mask = DEVICE_STATE.MASK_ALL if include_inactive else DEVICE_STATE.ACTIVE
    coll = enum.EnumAudioEndpoints(flow, mask.value)
    default = _default_id(enum, flow, ERole.eConsole.value)
    return [_to_device(coll.Item(i), default) for i in range(coll.GetCount())]


def get_default_audio_device(
    flow: int = EDataFlow.eRender.value, role: int = ERole.eConsole.value
) -> AudioDevice | None:
    enum = _enumerator()
    try:
        dev = enum.GetDefaultAudioEndpoint(flow, role)
    except comtypes.COMError:
        return None
    return _to_device(dev, dev.GetId())


def set_default_audio_device(device_id: str, roles=ALL_ROLES) -> None:
    """Make ``device_id`` the default playback endpoint for the given roles."""
    comtypes.CoInitialize()
    AudioUtilities.SetDefaultDevice(device_id, roles=list(roles))
