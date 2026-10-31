"""Automatic mode switching driven by which input devices are in use.

Three layers, the first two pure Python and unit-tested:

* ``WiggleDetector`` decides whether recent relative mouse motion is a
  deliberate wiggle (lots of travel *and* direction reversals in a short
  window) rather than sensor drift or a bumped desk.
* ``Policy`` is the state machine: maps device events to "switch to mode X"
  decisions, honouring the current mode, a cooldown after each switch and an
  in-progress switch. The current mode is re-read from the system after any
  display change and periodically, so manual switches are picked up.
* ``Watcher`` glues them to ``rawinput.RawInputListener`` and ``modes.apply``;
  switches run on a worker thread so the message pump keeps going.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import AutoConfig, Config, Trigger
from .modes import Backend, apply, current_mode
from .rawinput import InputDevice, InputEvent, RawInputListener
from .tray import SEPARATOR, MenuItem, Tray, TrayState, mode_color

log = logging.getLogger("tvmode.auto")


# --------------------------------------------------------------------------- #
# Wiggle detection
# --------------------------------------------------------------------------- #


def count_reversals(values: list[int]) -> int:
    """Number of sign changes in a sequence of deltas, ignoring zeros."""
    n = 0
    last = 0
    for v in values:
        if v == 0:
            continue
        s = 1 if v > 0 else -1
        if last and s != last:
            n += 1
        last = s
    return n


class WiggleDetector:
    """Feed relative mouse deltas; ``feed`` returns True once the motion in
    the trailing ``window`` seconds covers at least ``min_distance`` counts
    *and* reverses direction at least ``min_reversals`` times on one axis.

    Drift is a few counts in one direction; a desk bump is one direction too.
    Only a deliberate back-and-forth satisfies both conditions."""

    def __init__(
        self, window: float = 1.5, min_distance: float = 300.0, min_reversals: int = 2
    ) -> None:
        self.window = window
        self.min_distance = min_distance
        self.min_reversals = min_reversals
        self._events: deque[tuple[float, int, int]] = deque()

    def reset(self) -> None:
        self._events.clear()

    def feed(self, dx: int, dy: int, now: float) -> bool:
        ev = self._events
        ev.append((now, dx, dy))
        cutoff = now - self.window
        while ev and ev[0][0] < cutoff:
            ev.popleft()
        distance = sum(math.hypot(x, y) for _, x, y in ev)
        if distance < self.min_distance:
            return False
        xs = [x for _, x, _ in ev]
        ys = [y for _, _, y in ev]
        if max(count_reversals(xs), count_reversals(ys)) < self.min_reversals:
            return False
        ev.clear()  # fire once per wiggle
        return True


# --------------------------------------------------------------------------- #
# Policy (state machine)
# --------------------------------------------------------------------------- #


@dataclass
class Decision:
    mode: str
    reason: str


@dataclass
class Policy:
    """Decides when a device event should cause a switch.

    ``current`` is the mode believed to be in effect (None = unknown).
    Triggers for the current mode are ignored; so is everything while a
    switch is running or during the cooldown after one.

    ``pending`` is a switch that failed only because its devices were not
    connected (monitors unplugged, TV off). It is retried whenever hardware
    changes until ``pending_timeout`` runs out, it succeeds, or a trigger for
    the current mode says the user is staying put."""

    auto: AutoConfig
    current: str | None = None
    busy: bool = False
    cooldown_until: float = float("-inf")
    pending: str | None = None
    pending_until: float = float("-inf")
    _wiggles: dict[int, WiggleDetector] = field(default_factory=dict)

    def _wiggle(self, handle: int) -> WiggleDetector:
        w = self._wiggles.get(handle)
        if w is None:
            a = self.auto
            w = WiggleDetector(a.wiggle_window, a.wiggle_distance, a.wiggle_reversals)
            self._wiggles[handle] = w
        return w

    def feed(self, ev: InputEvent, mode: str, now: float) -> Decision | None:
        """``mode`` is the mode the event's device is a trigger for."""
        if ev.kind == "keyboard":
            if not ev.key_down:
                return None
            reason = "keyboard"
        elif ev.kind == "mouse":
            # Always feed the detector, even when suppressed, so its window
            # reflects real motion; but only act when allowed.
            if not self._wiggle(ev.handle).feed(ev.dx, ev.dy, now):
                return None
            reason = "mouse wiggle"
        else:
            return None

        if self.busy:
            return None
        if mode == self.current:
            self.pending = None  # back on this mode's devices: staying put
            return None
        if now < self.cooldown_until:
            return None
        return Decision(mode=mode, reason=reason)

    def switch_started(self) -> None:
        self.busy = True

    def observe(self, mode: str | None) -> bool:
        """Record the mode actually in effect, as read from the system.
        Ignored while a switch is running (its result is authoritative).
        Returns True if this changed what the policy believed."""
        if self.busy or mode == self.current:
            return False
        self.current = mode
        return True

    def switch_finished(
        self,
        mode: str | None,
        ok: bool,
        now: float,
        *,
        target: str | None = None,
        devices_missing: bool = False,
        retry: bool = False,
    ) -> None:
        """``mode`` is the mode now believed in effect (None if unknown).
        ``target`` is the mode that was attempted; ``devices_missing`` means
        it failed only because something wasn't connected, so it stays
        pending. ``retry`` marks a retry of a pending switch: a failed retry
        changed nothing, so it neither starts a cooldown nor resets wiggles."""
        self.busy = False
        if ok:
            self.current = mode
            self.pending = None
        elif devices_missing and target is not None:
            if self.pending != target:
                self.pending = target
                self.pending_until = now + self.auto.pending_timeout
        else:
            self.pending = None
        if ok or not retry:
            self.cooldown_until = now + self.auto.cooldown
            for w in self._wiggles.values():
                w.reset()

    def due_retry(self, now: float) -> str | None:
        """The pending mode to retry now, if any. Drops it once expired or
        once that mode is in effect anyway."""
        if self.pending is None or self.busy:
            return None
        if now >= self.pending_until or self.pending == self.current:
            self.pending = None
            return None
        return self.pending


# --------------------------------------------------------------------------- #
# Device -> trigger mapping
# --------------------------------------------------------------------------- #


def _matches(matcher: str, device: InputDevice) -> bool:
    m = matcher.strip().lower()
    return bool(m) and any(m in k.lower() for k in device.match_keys() if k)


def map_devices(
    devices: list[InputDevice], triggers: dict[str, Trigger]
) -> tuple[dict[int, str], list[str]]:
    """Return ``{device handle: mode}`` plus warnings for matchers that hit
    nothing. One physical keyboard often appears as several raw devices
    (one per USB interface), so every matching device is mapped, not just
    one. A device claimed by two modes is dropped with a warning."""
    mapping: dict[int, str] = {}
    conflicts: set[int] = set()
    warnings: list[str] = []
    for trig in triggers.values():
        for kind, matchers in (("keyboard", trig.keyboards), ("mouse", trig.mice)):
            for m in matchers:
                hits = [d for d in devices if d.kind == kind and _matches(m, d)]
                if not hits:
                    warnings.append(f"no {kind} matches {m!r} (for mode {trig.mode})")
                for d in hits:
                    prev = mapping.get(d.handle)
                    if prev is not None and prev != trig.mode:
                        conflicts.add(d.handle)
                        warnings.append(
                            f"{kind} {d.label} ({d.vid_pid}) matches both "
                            f"{prev} and {trig.mode}; ignoring it"
                        )
                    mapping[d.handle] = trig.mode
    for h in conflicts:
        mapping.pop(h, None)
    return mapping, warnings


# --------------------------------------------------------------------------- #
# Watcher (glue)
# --------------------------------------------------------------------------- #


class Watcher:
    """Runs the listener and applies modes. ``list_devices`` and ``clock``
    are injectable for tests."""

    def __init__(
        self,
        cfg: Config,
        backend: Backend,
        *,
        dry_run: bool = False,
        debug: bool = False,
        list_devices: Callable[[], list[InputDevice]] | None = None,
        clock: Callable[[], float] | None = None,
        log_path: Path | None = None,
    ) -> None:
        if cfg.auto is None:
            raise ValueError("config has no [auto] section")
        self.cfg = cfg
        self.auto: AutoConfig = cfg.auto
        self.backend = backend
        self.dry_run = dry_run
        self.debug = debug
        if list_devices is None:
            from .rawinput import list_input_devices

            list_devices = list_input_devices
        self._list_devices = list_devices
        if clock is None:
            import time

            clock = time.monotonic
        self._clock = clock
        self.policy = Policy(cfg.auto)
        self._lock = threading.Lock()
        self._devices: dict[int, InputDevice] = {}
        self._mapping: dict[int, str] = {}
        self._listener: RawInputListener | None = None
        self._device_summary: list[str] = []
        self.paused = False
        self.log_path = log_path
        self._tray: Tray | None = None

    # -- devices ---------------------------------------------------------- #
    def refresh_devices(self) -> None:
        devices = self._list_devices()
        mapping, warnings = map_devices(devices, self.auto.triggers)
        with self._lock:
            self._devices = {d.handle: d for d in devices}
            self._mapping = mapping
        for w in warnings:
            log.warning(w)
        by_mode: dict[str, list[str]] = {}
        for h, mode in mapping.items():
            d = self._devices[h]
            by_mode.setdefault(mode, []).append(f"{d.kind}:{d.vid_pid or d.label}")
        summary = [
            f"mode {mode} <- {', '.join(sorted(set(names)))}"
            for mode, names in sorted(by_mode.items())
        ]
        if summary != self._device_summary:  # Windows repeats arrivals at startup
            self._device_summary = summary
            for line in summary:
                log.info(line)

    def check_state(self) -> None:
        """Re-read which mode is in effect, so a switch made outside watch
        (hotkey, `tvmode apply`, Win+P) does not leave the policy believing
        a stale mode and ignoring the triggers that should undo it."""
        if self.policy.busy:
            return
        before = self.policy.current
        cur = current_mode(self.cfg.modes, self.backend)
        if self.policy.observe(cur):
            log.info(
                "mode changed outside watch: %s -> %s",
                before or "unknown",
                cur or "unknown",
            )
            self._tray_changed()
        if self.paused:
            return
        waiting = self.policy.pending
        target = self.policy.due_retry(self._clock())
        if target is None:
            if waiting is not None and self.policy.pending is None:
                if self.policy.current == waiting:
                    log.info("now in %s; no longer waiting", waiting)
                else:
                    log.info("gave up waiting for the %s devices", waiting)
                self._tray_changed()
            return
        log.debug("hardware changed; retrying switch to %s", target)
        self._start_switch(target, retry=True)

    # -- events ----------------------------------------------------------- #
    def on_event(self, ev: InputEvent) -> None:
        with self._lock:
            mode = self._mapping.get(ev.handle)
            dev = self._devices.get(ev.handle)
        if self.debug:
            who = (
                f"{dev.kind} {dev.vid_pid or dev.label}"
                if dev
                else f"handle {ev.handle:#x}"
            )
            if ev.kind == "mouse":
                log.debug("%s -> %s  dx=%+d dy=%+d", who, mode or "-", ev.dx, ev.dy)
            elif ev.key_down:
                log.debug("%s -> %s  key down", who, mode or "-")
        if mode is None or self.paused:
            return
        decision = self.policy.feed(ev, mode, self._clock())
        if decision is None:
            return
        log.info("%s on %s device -> switching to %s", decision.reason, mode, mode)
        self._start_switch(decision.mode)

    def _start_switch(self, target: str, *, retry: bool = False) -> None:
        self.policy.switch_started()
        threading.Thread(
            target=self._switch,
            args=(target, retry),
            daemon=True,
            name="tvmode-switch",
        ).start()

    def _switch(self, target: str, retry: bool = False) -> None:
        ok = True
        missing = False
        result_mode: str | None = target
        try:
            # Someone may have switched manually since we last looked.
            cur = current_mode(self.cfg.modes, self.backend)
            if cur == target:
                log.info("already in %s", target)
                return
            res = apply(self.cfg.mode(target), self.backend, dry_run=self.dry_run)
            ok = res.ok
            missing = res.devices_missing and not self.dry_run
            if retry and missing:
                # Still not connected; stay quiet, the next change retries.
                for e in res.errors:
                    log.debug(e)
                return
            if retry and ok:
                log.info("devices for %s connected; switching", target)
            for m in res.messages:
                log.info(m)
            for e in res.errors:
                log.error(e)
            if missing:
                log.info(
                    "will switch to %s when its devices are connected "
                    "(waiting up to %gs)",
                    target,
                    self.auto.pending_timeout,
                )
            if self.dry_run:
                result_mode = cur
        except Exception:
            log.exception("switch to %s failed", target)
            ok = False
        finally:
            self.policy.switch_finished(
                result_mode if ok else None,
                ok,
                self._clock(),
                target=target,
                devices_missing=missing,
                retry=retry,
            )
            self._tray_changed()

    # -- tray ------------------------------------------------------------- #
    def tray_state(self) -> TrayState:
        cur = self.policy.current
        pending = self.policy.pending
        tip = f"tvmode: {cur or 'unknown mode'}"
        if pending:
            tip += f" (waiting for {pending} devices)"
        if self.paused:
            tip += " - paused"
        if self.dry_run:
            tip += " - dry run"
        menu = [MenuItem(f"Current mode: {cur or 'unknown'}"), SEPARATOR]
        for name in self.cfg.modes:
            menu.append(
                MenuItem(
                    f"Switch to {name}",
                    f"switch:{name}",
                    checked=name == cur,
                    enabled=not self.policy.busy,
                )
            )
        menu += [
            SEPARATOR,
            MenuItem("Pause auto-switching", "pause", checked=self.paused),
            MenuItem("Open log", "log", enabled=self.log_path is not None),
            SEPARATOR,
            MenuItem("Quit", "quit"),
        ]
        return TrayState(tip, mode_color(cur, list(self.cfg.modes)), menu)

    def on_tray_command(self, command: str) -> None:
        if command.startswith("switch:"):
            target = command.split(":", 1)[1]
            if self.policy.busy:
                return
            log.info("tray -> switching to %s", target)
            self.policy.pending = None
            self._start_switch(target)
        elif command == "pause":
            self.paused = not self.paused
            if self.paused:
                self.policy.pending = None
            log.info("auto-switching %s", "paused" if self.paused else "resumed")
            self._tray_changed()
        elif command == "log" and self.log_path is not None:
            os.startfile(self.log_path)  # type: ignore[attr-defined]  # Windows only
        elif command == "quit":
            log.info("quit from tray")
            self.stop()

    def _tray_changed(self) -> None:
        if self._tray is not None:
            self._tray.request_update()

    def _attach_tray(self, hwnd: int) -> None:
        if self._tray is None:
            return
        try:
            self._tray.attach(hwnd)
        except Exception:
            log.exception("could not add the tray icon; continuing without it")
            self._tray = None

    # -- lifecycle -------------------------------------------------------- #
    def run(self, *, tray: bool = False) -> None:
        self.policy.current = current_mode(self.cfg.modes, self.backend)
        log.info("current mode: %s", self.policy.current or "unknown")
        self.refresh_devices()
        if tray:
            self._tray = Tray(self.tray_state, self.on_tray_command)
        self._listener = RawInputListener(
            self.on_event,
            on_devices_changed=self.refresh_devices,
            on_state_check=self.check_state,
            display_settle=2.0,  # give a just-plugged monitor time to show up
            on_error=lambda e: log.exception("callback failed: %s", e),
            on_window=self._attach_tray,
            on_message=self._tray_message,
        )
        log.info("watching for input%s", " (dry run)" if self.dry_run else "")
        self._listener.run()

    def _tray_message(self, hwnd: int, msg: int, wp: int, lp: int) -> int | None:
        return self._tray.handle(hwnd, msg, wp, lp) if self._tray else None

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
