"""Apply a configured mode: resolve matchers to devices, switch, verify.

All OS access goes through a ``Backend`` so the engine can be tested with a
fake. ``WindowsBackend`` is the real one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from .audio import AudioDevice
from .config import Mode
from .display import DisplayInfo, TargetKey
from .matching import DeviceMissing, MatchError, match_one


class Backend(Protocol):
    def list_displays(self) -> list[DisplayInfo]: ...
    def active_targets(self) -> set[TargetKey]: ...
    def set_active_displays(self, wanted: set[TargetKey]) -> None: ...
    def check_displays(self, wanted: set[TargetKey]) -> None: ...
    def list_audio(self) -> list[AudioDevice]: ...
    def default_audio_id(self) -> str | None: ...
    def set_default_audio(self, device_id: str) -> None: ...
    def sleep(self, seconds: float) -> None: ...


class WindowsBackend:
    def list_displays(self) -> list[DisplayInfo]:
        from . import display

        return display.list_displays()

    def active_targets(self) -> set[TargetKey]:
        from . import display

        return display.active_targets()

    def set_active_displays(self, wanted: set[TargetKey]) -> None:
        from . import display

        display.set_active_displays(wanted)

    def check_displays(self, wanted: set[TargetKey]) -> None:
        """Raise if ``wanted`` could not be made active; changes nothing."""
        from . import display

        display.set_active_displays(wanted, validate_only=True)

    def list_audio(self) -> list[AudioDevice]:
        from . import audio

        return audio.list_audio_devices()

    def default_audio_id(self) -> str | None:
        from . import audio

        dev = audio.get_default_audio_device()
        return dev.id if dev else None

    def set_default_audio(self, device_id: str) -> None:
        from . import audio

        audio.set_default_audio_device(device_id)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass
class Plan:
    """What applying a mode would do."""

    mode: str
    displays: list[DisplayInfo] = field(default_factory=list)
    audio: AudioDevice | None = None
    display_change_needed: bool = False
    audio_change_needed: bool = False


@dataclass
class Result:
    mode: str
    ok: bool
    display_changed: bool = False
    audio_changed: bool = False
    rolled_back: bool = False
    devices_missing: bool = False  # failed only because something isn't connected
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _display_keys(d: DisplayInfo):
    return (d.friendly_name, d.device_path, d.gdi_name)


def _audio_keys(a: AudioDevice):
    return (a.name, a.id)


def resolve(mode: Mode, backend: Backend, *, do_display=True, do_audio=True) -> Plan:
    """Resolve a mode's matchers against the current devices. Raises
    ``MatchError`` if anything is missing or ambiguous."""
    plan = Plan(mode=mode.name)

    if do_display and mode.displays:
        displays = [d for d in backend.list_displays() if d.available]
        chosen: list[DisplayInfo] = []
        for m in mode.displays:
            d = match_one(m, displays, _display_keys, lambda d: d.label, kind="display")
            if d in chosen:
                raise MatchError(
                    f"display matcher {m!r} resolves to an already-chosen display"
                )
            chosen.append(d)
        plan.displays = chosen
        wanted = {d.target for d in chosen}
        plan.display_change_needed = backend.active_targets() != wanted

    if do_audio and mode.audio:
        devices = backend.list_audio()
        a = match_one(
            mode.audio, devices, _audio_keys, lambda a: a.label, kind="audio device"
        )
        plan.audio = a
        plan.audio_change_needed = backend.default_audio_id() != a.id

    return plan


def _switch_displays(
    backend: Backend,
    wanted: set[TargetKey],
    names: str,
    res: Result,
    *,
    verify_retries: int,
    verify_delay: float,
) -> None:
    try:
        backend.set_active_displays(wanted)
        for _ in range(verify_retries):
            if backend.active_targets() == wanted:
                break
            backend.sleep(verify_delay)
        else:
            raise RuntimeError(
                f"display change did not take effect (active={backend.active_targets()}, wanted={wanted})"
            )
        res.display_changed = True
        res.messages.append(f"displays -> {names}")
    except Exception as e:  # noqa: BLE001 - report every failure
        res.ok = False
        res.errors.append(f"display: {e}")


def _switch_audio(
    backend: Backend,
    device_id: str,
    name: str,
    res: Result,
    *,
    verify_retries: int,
    verify_delay: float,
) -> None:
    try:
        backend.set_default_audio(device_id)
        for _ in range(verify_retries):
            if backend.default_audio_id() == device_id:
                break
            backend.sleep(verify_delay)
        else:
            raise RuntimeError("audio device change did not take effect")
        res.audio_changed = True
        res.messages.append(f"audio -> {name}")
    except Exception as e:  # noqa: BLE001
        res.ok = False
        res.errors.append(f"audio: {e}")


def apply(
    mode: Mode,
    backend: Backend,
    *,
    do_display: bool = True,
    do_audio: bool = True,
    dry_run: bool = False,
    verify_retries: int = 3,
    verify_delay: float = 1.0,
) -> Result:
    """Switch to ``mode``, all or nothing: display and audio either both end
    up in the requested state or neither is changed.

    Everything is checked before anything is touched (every matcher resolves
    to a connected device, Windows accepts the display layout). Audio is
    switched first because undoing it is invisible; if either half then fails
    or does not verify, whatever already changed is rolled back."""
    res = Result(mode=mode.name, ok=True)

    try:
        plan = resolve(mode, backend, do_display=do_display, do_audio=do_audio)
    except MatchError as e:
        res.ok = False
        res.devices_missing = isinstance(e, DeviceMissing)
        res.errors.append(f"{e}; nothing was changed")
        return res

    wanted = {d.target for d in plan.displays}
    display_names = ", ".join(d.label for d in plan.displays)

    # ---- preflight: refuse up front rather than switch half -------------- #
    if plan.display_change_needed:
        try:
            backend.check_displays(wanted)
        except Exception as e:  # noqa: BLE001
            res.ok = False
            res.errors.append(
                f"display: cannot activate {display_names}: {e}; nothing was changed"
            )
            return res

    if plan.displays and not plan.display_change_needed:
        res.messages.append(f"displays already set: {display_names}")
    if plan.audio and not plan.audio_change_needed:
        res.messages.append(f"audio already set: {plan.audio.label}")

    if dry_run:
        if plan.display_change_needed:
            res.messages.append(f"would activate displays: {display_names}")
        if plan.audio and plan.audio_change_needed:
            res.messages.append(f"would set default audio: {plan.audio.label}")
        return res

    if not (plan.display_change_needed or plan.audio_change_needed):
        return res

    before = snapshot(backend)
    vr, vd = verify_retries, verify_delay

    if plan.audio and plan.audio_change_needed:
        a = plan.audio
        _switch_audio(backend, a.id, a.label, res, verify_retries=vr, verify_delay=vd)
    if res.ok and plan.display_change_needed:
        _switch_displays(
            backend, wanted, display_names, res, verify_retries=vr, verify_delay=vd
        )

    if not res.ok:
        back = restore(
            before,
            backend,
            do_display=do_display,
            do_audio=do_audio,
            verify_retries=vr,
            verify_delay=vd,
        )
        _record_rollback(res, back)
    return res


def _record_rollback(res: Result, back: Result) -> None:
    """Fold the outcome of undoing a partly applied switch into ``res``."""
    changed = [m for m in back.messages if "already set" not in m]
    if back.ok:
        res.rolled_back = True
        if changed:
            res.messages.append("rolled back: " + "; ".join(changed))
        res.errors.append("nothing was changed (rolled back)")
    else:
        res.errors.extend(f"rollback failed: {e}" for e in back.errors)
        res.errors.append("setup may be half switched; check `tvmode status`")


@dataclass(frozen=True)
class Snapshot:
    """The raw device state at some moment, independent of any configured
    mode, so it can be restored even if the current setup matches no mode."""

    displays: frozenset[TargetKey]
    display_names: str
    audio_id: str | None
    audio_name: str


def snapshot(backend: Backend) -> Snapshot:
    """Capture the currently active displays and default audio device."""
    active = [d for d in backend.list_displays() if d.active]
    audio_id = backend.default_audio_id()
    audio_name = next(
        (a.label for a in backend.list_audio() if a.id == audio_id),
        audio_id or "(none)",
    )
    return Snapshot(
        displays=frozenset(d.target for d in active),
        display_names=", ".join(d.label for d in active) or "(none)",
        audio_id=audio_id,
        audio_name=audio_name,
    )


def restore(
    snap: Snapshot,
    backend: Backend,
    *,
    do_display: bool = True,
    do_audio: bool = True,
    verify_retries: int = 3,
    verify_delay: float = 1.0,
) -> Result:
    """Put the devices back to the state captured by ``snapshot``. Each half
    is skipped if it is already in that state."""
    res = Result(mode="(previous setup)", ok=True)

    if do_display and snap.displays:
        if backend.active_targets() == set(snap.displays):
            res.messages.append(f"displays already set: {snap.display_names}")
        else:
            _switch_displays(
                backend,
                set(snap.displays),
                snap.display_names,
                res,
                verify_retries=verify_retries,
                verify_delay=verify_delay,
            )

    if do_audio and snap.audio_id:
        if backend.default_audio_id() == snap.audio_id:
            res.messages.append(f"audio already set: {snap.audio_name}")
        else:
            _switch_audio(
                backend,
                snap.audio_id,
                snap.audio_name,
                res,
                verify_retries=verify_retries,
                verify_delay=verify_delay,
            )

    return res


def current_mode(modes: dict[str, Mode], backend: Backend) -> str | None:
    """Return the name of the mode whose devices are all currently in effect,
    or None if no configured mode matches."""
    for name, mode in modes.items():
        try:
            plan = resolve(mode, backend)
        except MatchError:
            continue
        if plan.display_change_needed or plan.audio_change_needed:
            continue
        if not plan.displays and plan.audio is None:
            continue
        return name
    return None
