import threading

import pytest
from fake_backend import MON1, MON2, TV, FakeBackend

from tvmode.auto import (
    Policy,
    Watcher,
    WiggleDetector,
    count_reversals,
    map_devices,
)
from tvmode.config import AutoConfig, ConfigError, Trigger, parse_config
from tvmode.modes import apply
from tvmode.rawinput import InputDevice, InputEvent

CONFIG = """
[modes.game]
displays = ["S24C570", "LG ULTRAGEAR"]
audio = "Realtek HD Audio 2nd output"

[modes.tv]
displays = ["SAMSUNG"]
audio = "Realtek Digital Output"

[auto]
cooldown = 30
wiggle_window = 1.5
wiggle_distance = 300
wiggle_reversals = 2

[auto.modes.game]
keyboards = ["VID_308F"]
mice = ["VID_3151"]

[auto.modes.tv]
keyboards = ["VID_04D9&PID_FC40"]
"""

GAME_KB1 = InputDevice(0x11, "keyboard", r"\\?\HID#VID_308F&PID_0011&MI_00#a#{g}")
GAME_KB2 = InputDevice(0x12, "keyboard", r"\\?\HID#VID_308F&PID_0011&MI_01#b#{g}")
GAME_MOUSE = InputDevice(0x13, "mouse", r"\\?\HID#VID_3151&PID_3000&MI_01#c#{g}")
TV_KB = InputDevice(0x21, "keyboard", r"\\?\HID#VID_04D9&PID_FC40&MI_01#d#{g}")
TV_MOUSE = InputDevice(0x22, "mouse", r"\\?\HID#VID_04D9&PID_FC40&MI_00#e#{g}")
OTHER_KB = InputDevice(0x31, "keyboard", r"\\?\ROOT#FEIZHI_VIRTUAL_KEYBOARD#0000#{g}")
DEVICES = [GAME_KB1, GAME_KB2, GAME_MOUSE, TV_KB, TV_MOUSE, OTHER_KB]


def key(handle, down=True):
    return InputEvent("keyboard", handle, key_down=down)


def move(handle, dx, dy=0):
    return InputEvent("mouse", handle, dx=dx, dy=dy)


# ---- config --------------------------------------------------------------- #


def test_parse_auto_section():
    cfg = parse_config(CONFIG)
    assert cfg.auto is not None
    assert cfg.auto.cooldown == 30
    assert cfg.auto.wiggle_reversals == 2
    assert cfg.auto.triggers["game"].keyboards == ["VID_308F"]
    assert cfg.auto.triggers["game"].mice == ["VID_3151"]
    assert cfg.auto.triggers["tv"].mice == []


def test_parse_without_auto_is_fine():
    cfg = parse_config(CONFIG.split("[auto]")[0])
    assert cfg.auto is None


@pytest.mark.parametrize(
    "extra, msg",
    [
        ("[auto.modes.couch]\nkeyboards = ['x']", "unknown mode"),
        ("[auto.modes.tv]\n", "keyboards and/or mice"),
        (
            "[auto]\ncooldown = -1\n[auto.modes.tv]\nkeyboards = ['x']",
            "positive number",
        ),
        (
            "[auto]\nwiggle_reversals = 1.5\n[auto.modes.tv]\nkeyboards = ['x']",
            "positive integer",
        ),
        ("[auto]\nbogus = 1\n[auto.modes.tv]\nkeyboards = ['x']", "unknown keys"),
        ("[auto.modes.tv]\nkeyboards = ['x']\ntouchpads = ['y']", "unknown keys"),
    ],
)
def test_parse_auto_errors(extra, msg):
    base = CONFIG.split("[auto]")[0]
    with pytest.raises(ConfigError, match=msg):
        parse_config(base + extra)


# ---- wiggle --------------------------------------------------------------- #


def test_count_reversals():
    assert count_reversals([]) == 0
    assert count_reversals([1, 2, 3]) == 0
    assert count_reversals([1, 0, -1]) == 1
    assert count_reversals([5, -5, 5, -5]) == 3
    assert count_reversals([0, 0, 3, 0, 0, -3, 0, 3]) == 2


def test_drift_does_not_trigger():
    w = WiggleDetector(window=1.5, min_distance=300, min_reversals=2)
    # one count every 10ms in the same direction for 1.5s = 150 counts, no reversal
    assert not any(w.feed(1, 0, i * 0.01) for i in range(150))


def test_single_direction_bump_does_not_trigger():
    w = WiggleDetector(window=1.5, min_distance=300, min_reversals=2)
    assert not any(
        w.feed(40, 5, i * 0.01) for i in range(20)
    )  # 800+ counts, no reversal


def test_slow_back_and_forth_outside_window_does_not_trigger():
    w = WiggleDetector(window=1.5, min_distance=300, min_reversals=2)
    t = 0.0
    fired = False
    for direction in (1, -1, 1, -1):
        for _ in range(10):
            fired |= w.feed(20 * direction, 0, t)
            t += 0.2  # each leg takes 2s > window
    assert not fired


def test_deliberate_wiggle_triggers_once_then_resets():
    w = WiggleDetector(window=1.5, min_distance=300, min_reversals=2)
    t = 0.0
    fired = []
    for direction in (1, -1, 1):
        for _ in range(10):
            fired.append(w.feed(20 * direction, 3, t))
            t += 0.02
    assert fired.count(True) == 1
    assert fired.index(True) >= 20  # only after the second reversal
    # detector was cleared: same motion again is needed to fire again
    assert not w.feed(20, 0, t)


def test_vertical_wiggle_counts_too():
    w = WiggleDetector(window=1.5, min_distance=300, min_reversals=2)
    t = 0.0
    fired = False
    for direction in (1, -1, 1):
        for _ in range(10):
            fired |= w.feed(0, 20 * direction, t)
            t += 0.02
    assert fired


# ---- device mapping --------------------------------------------------------- #


def test_map_devices_maps_every_matching_interface():
    cfg = parse_config(CONFIG)
    mapping, warnings = map_devices(DEVICES, cfg.auto.triggers)
    assert mapping == {
        GAME_KB1.handle: "game",
        GAME_KB2.handle: "game",
        GAME_MOUSE.handle: "game",
        TV_KB.handle: "tv",
    }
    assert warnings == []


def test_map_devices_respects_kind():
    # "VID_04D9" as a *mouse* matcher for tv must not claim the tv keyboard
    trig = {"tv": Trigger("tv", mice=["VID_04D9"])}
    mapping, _ = map_devices(DEVICES, trig)
    assert mapping == {TV_MOUSE.handle: "tv"}


def test_map_devices_warns_on_missing_and_conflicts():
    trig = {
        "game": Trigger("game", keyboards=["HID#"]),
        "tv": Trigger("tv", keyboards=["VID_04D9"], mice=["nonexistent"]),
    }
    mapping, warnings = map_devices(DEVICES, trig)
    assert TV_KB.handle not in mapping  # claimed by both -> dropped
    assert mapping[GAME_KB1.handle] == "game"
    assert any("no mouse matches 'nonexistent'" in w for w in warnings)
    assert any("matches both game and tv" in w for w in warnings)


# ---- policy ------------------------------------------------------------------ #


def auto():
    return AutoConfig(
        cooldown=30, wiggle_window=1.5, wiggle_distance=300, wiggle_reversals=2
    )


def test_policy_keyboard_switches_only_to_other_mode():
    p = Policy(auto(), current="game")
    assert p.feed(key(GAME_KB1.handle), "game", 0.0) is None
    assert p.feed(key(TV_KB.handle, down=False), "tv", 0.0) is None  # release
    d = p.feed(key(TV_KB.handle), "tv", 0.0)
    assert d is not None and d.mode == "tv" and d.reason == "keyboard"


def test_policy_unknown_current_switches_on_anything():
    p = Policy(auto(), current=None)
    assert p.feed(key(GAME_KB1.handle), "game", 0.0).mode == "game"


def test_policy_busy_and_cooldown():
    p = Policy(auto(), current="game")
    p.switch_started()
    assert p.feed(key(TV_KB.handle), "tv", 1.0) is None
    p.switch_finished("tv", ok=True, now=10.0)
    assert p.current == "tv"
    # within cooldown: game keyboard ignored
    assert p.feed(key(GAME_KB1.handle), "game", 20.0) is None
    # after cooldown: honoured
    assert p.feed(key(GAME_KB1.handle), "game", 40.1).mode == "game"


def test_policy_failed_switch_keeps_current_and_cools_down():
    p = Policy(auto(), current="game")
    p.switch_started()
    p.switch_finished(None, ok=False, now=0.0)
    assert p.current == "game"
    assert p.feed(key(TV_KB.handle), "tv", 5.0) is None
    assert p.feed(key(TV_KB.handle), "tv", 31.0).mode == "tv"


def test_policy_mouse_needs_wiggle():
    p = Policy(auto(), current="tv")
    t = 0.0
    decisions = []
    for direction in (1, -1, 1):
        for _ in range(10):
            decisions.append(p.feed(move(GAME_MOUSE.handle, 20 * direction), "game", t))
            t += 0.02
    real = [d for d in decisions if d]
    assert (
        len(real) == 1 and real[0].mode == "game" and real[0].reason == "mouse wiggle"
    )


# ---- watcher (no Raw Input; drive on_event directly) ------------------------- #


class SyncThread:
    """Run the target inline so tests do not need to join threads."""

    def __init__(self, target, args=(), **_):
        self._t, self._a = target, args

    def start(self):
        self._t(*self._a)


@pytest.fixture
def sync_threads(monkeypatch):
    monkeypatch.setattr(threading, "Thread", SyncThread)


def make_watcher(backend, dry_run=False):
    cfg = parse_config(CONFIG)
    clock = {"t": 0.0}
    w = Watcher(
        cfg,
        backend,
        dry_run=dry_run,
        list_devices=lambda: DEVICES,
        clock=lambda: clock["t"],
    )
    w.policy.current = "game"
    w.refresh_devices()
    return w, clock


def test_watcher_switches_on_tv_keyboard(sync_threads):
    b = FakeBackend()
    w, _ = make_watcher(b)
    w.on_event(key(TV_KB.handle))
    assert b.active_targets() == {TV.target}
    assert b.default_audio_id() == "id-spk"
    assert w.policy.current == "tv"
    assert not w.policy.busy


def test_watcher_ignores_unmapped_and_same_mode_devices(sync_threads):
    b = FakeBackend()
    w, _ = make_watcher(b)
    w.on_event(key(OTHER_KB.handle))
    w.on_event(key(GAME_KB1.handle))
    w.on_event(key(0xDEAD))
    assert b.set_display_calls == []


def test_watcher_cooldown_blocks_flapping(sync_threads):
    b = FakeBackend()
    w, clock = make_watcher(b)
    w.on_event(key(TV_KB.handle))
    clock["t"] = 5.0
    w.on_event(key(GAME_KB1.handle))  # inside cooldown
    assert len(b.set_display_calls) == 1
    clock["t"] = 45.0
    w.on_event(key(GAME_KB1.handle))
    assert len(b.set_display_calls) == 2
    assert w.policy.current == "game"


def test_watcher_dry_run_changes_nothing(sync_threads):
    b = FakeBackend()
    w, _ = make_watcher(b, dry_run=True)
    w.on_event(key(TV_KB.handle))
    assert b.set_display_calls == []
    assert w.policy.current == "game"


def test_watcher_notices_manual_switch(sync_threads):
    b = FakeBackend()
    w, _ = make_watcher(b)
    # user ran `tvmode apply tv` behind our back
    b.set_active_displays({TV.target})
    b.set_default_audio("id-spk")
    calls = len(b.set_display_calls)
    w.on_event(key(TV_KB.handle))
    assert len(b.set_display_calls) == calls  # nothing re-applied
    assert w.policy.current == "tv"


def test_watcher_failed_switch_logs_and_recovers(sync_threads):
    b = FakeBackend()
    b.display_fail = RuntimeError("nope")
    w, clock = make_watcher(b)
    w.on_event(key(TV_KB.handle))
    assert w.policy.current == "game"
    assert not w.policy.busy
    clock["t"] = 60.0
    b.display_fail = None
    w.on_event(key(TV_KB.handle))
    assert w.policy.current == "tv"


def test_watcher_picks_up_manual_switch_so_desk_keyboard_switches_back(
    sync_threads,
):
    b = FakeBackend()
    w, _ = make_watcher(b)
    # user hit the tv hotkey; watch still believes "game"
    apply(w.cfg.mode("tv"), b)
    w.on_event(key(GAME_KB1.handle))
    assert b.active_targets() == {TV.target}  # stale belief: ignored
    w.check_state()  # what the display-change / poll timer does
    assert w.policy.current == "tv"
    w.on_event(key(GAME_KB1.handle))
    assert b.active_targets() == {MON1.target, MON2.target}
    assert w.policy.current == "game"


def test_check_state_ignored_while_switching():
    b = FakeBackend()
    w, _ = make_watcher(b)
    apply(w.cfg.mode("tv"), b)
    w.policy.switch_started()
    w.check_state()
    assert w.policy.current == "game"


def test_check_state_unknown_mode():
    b = FakeBackend()
    w, _ = make_watcher(b)
    b.set_default_audio("id-cable")  # matches no mode
    w.check_state()
    assert w.policy.current is None


def test_policy_pending_switch_lifecycle():
    p = Policy(auto(), current="tv")
    p.switch_started()
    p.switch_finished(None, ok=False, now=0.0, target="game", devices_missing=True)
    assert p.pending == "game"
    assert p.due_retry(10.0) == "game"
    # a failed retry keeps it pending and does not start a new cooldown
    p.switch_started()
    p.switch_finished(
        None, ok=False, now=40.0, target="game", devices_missing=True, retry=True
    )
    assert p.pending == "game" and p.cooldown_until == 30.0
    assert p.due_retry(299.0) == "game"
    assert p.due_retry(300.0) is None and p.pending is None  # timed out


def test_policy_touching_current_mode_cancels_pending():
    p = Policy(auto(), current="tv")
    p.switch_started()
    p.switch_finished(None, ok=False, now=0.0, target="game", devices_missing=True)
    assert p.feed(key(TV_KB.handle), "tv", 5.0) is None
    assert p.pending is None


def test_policy_other_failures_are_not_retried():
    p = Policy(auto(), current="tv")
    p.switch_started()
    p.switch_finished(None, ok=False, now=0.0, target="game")
    assert p.pending is None and p.due_retry(1.0) is None


def test_watcher_switches_once_monitors_are_plugged_in(sync_threads):
    b = FakeBackend()
    w, clock = make_watcher(b)
    apply(w.cfg.mode("tv"), b)
    w.check_state()
    assert w.policy.current == "tv"
    # monitors unplugged
    b.displays[0].available = b.displays[1].available = False
    calls = (len(b.set_display_calls), len(b.set_audio_calls))
    clock["t"] = 100.0
    w.on_event(key(GAME_KB1.handle))
    assert (len(b.set_display_calls), len(b.set_audio_calls)) == calls  # untouched
    assert b.active_targets() == {TV.target}
    assert w.policy.pending == "game"
    # hardware changes but monitors still missing: quiet retry, no change
    clock["t"] = 105.0
    w.check_state()
    assert b.active_targets() == {TV.target} and w.policy.pending == "game"
    # monitors plugged in (still inside the cooldown of the failed attempt)
    b.displays[0].available = b.displays[1].available = True
    clock["t"] = 110.0
    w.check_state()
    assert b.active_targets() == {MON1.target, MON2.target}
    assert b.default_audio_id() == "id-hp"
    assert w.policy.current == "game" and w.policy.pending is None


def test_watcher_gives_up_after_pending_timeout(sync_threads):
    b = FakeBackend()
    w, clock = make_watcher(b)
    apply(w.cfg.mode("tv"), b)
    w.check_state()
    b.displays[0].available = False
    clock["t"] = 100.0
    w.on_event(key(GAME_KB1.handle))
    assert w.policy.pending == "game"
    b.displays[0].available = True
    clock["t"] = 100.0 + w.auto.pending_timeout
    w.check_state()
    assert w.policy.pending is None
    assert b.active_targets() == {TV.target}


def test_watcher_requires_auto_section():
    cfg = parse_config(CONFIG.split("[auto]")[0])
    with pytest.raises(ValueError, match="no \\[auto\\]"):
        Watcher(cfg, FakeBackend(), list_devices=list)
