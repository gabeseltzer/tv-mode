"""In-memory Backend for testing the mode engine and CLI without Windows."""

from __future__ import annotations

from tvmode.audio import AudioDevice
from tvmode.display import DisplayInfo, TargetKey

A = 1
MON1 = DisplayInfo(
    (A, 100), "S24C570", r"\\?\DISPLAY#SAM0A59#x", "hdmi", True, True, r"\\.\DISPLAY1"
)
MON2 = DisplayInfo(
    (A, 101),
    "LG ULTRAGEAR",
    r"\\?\DISPLAY#GSM5B7F#x",
    "displayport",
    True,
    True,
    r"\\.\DISPLAY2",
)
TV = DisplayInfo((A, 102), "SAMSUNG", r"\\?\DISPLAY#SAM0D3B#x", "hdmi", False, True)

HEADPHONES = AudioDevice(
    "id-hp", "Realtek HD Audio 2nd output (Realtek(R) Audio)", "Active", True
)
SPEAKERS = AudioDevice(
    "id-spk", "Realtek Digital Output (Realtek(R) Audio)", "Active", False
)
CABLE = AudioDevice(
    "id-cable", "CABLE In 16ch (VB-Audio Virtual Cable)", "Active", False
)


class FakeBackend:
    def __init__(
        self,
        displays: list[DisplayInfo] | None = None,
        audio: list[AudioDevice] | None = None,
        default_audio: str = "id-hp",
    ) -> None:
        self.displays = [d for d in (displays or [MON1, MON2, TV])]
        # copy so tests can mutate freely
        self.displays = [
            DisplayInfo(
                d.target,
                d.friendly_name,
                d.device_path,
                d.output,
                d.active,
                d.available,
                d.gdi_name,
            )
            for d in self.displays
        ]
        self.audio = [
            AudioDevice(a.id, a.name, a.state, a.id == default_audio)
            for a in (audio or [HEADPHONES, SPEAKERS, CABLE])
        ]
        self._default = default_audio
        self.set_display_calls: list[set[TargetKey]] = []
        self.set_audio_calls: list[str] = []
        self.slept = 0.0
        # Failure injection
        self.display_fail: Exception | None = None
        self.display_check_fail: Exception | None = None
        self.audio_fail: Exception | None = None
        self.display_apply_silently_ignored = False
        self.audio_apply_silently_ignored = False

    # -- Backend protocol -------------------------------------------------
    def list_displays(self):
        return list(self.displays)

    def active_targets(self):
        return {d.target for d in self.displays if d.active}

    def set_active_displays(self, wanted):
        self.set_display_calls.append(set(wanted))
        if self.display_fail:
            raise self.display_fail
        if self.display_apply_silently_ignored:
            return
        for d in self.displays:
            d.active = d.target in wanted

    def check_displays(self, wanted):
        if self.display_check_fail:
            raise self.display_check_fail
        ok = {d.target for d in self.displays if d.available}
        if not set(wanted) <= ok:
            raise RuntimeError(f"targets not connected/available: {set(wanted) - ok}")

    def list_audio(self):
        return list(self.audio)

    def default_audio_id(self):
        return self._default

    def set_default_audio(self, device_id):
        self.set_audio_calls.append(device_id)
        if self.audio_fail:
            raise self.audio_fail
        if self.audio_apply_silently_ignored:
            return
        self._default = device_id
        for a in self.audio:
            a.is_default = a.id == device_id

    def sleep(self, seconds):
        self.slept += seconds
