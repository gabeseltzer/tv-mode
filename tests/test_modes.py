from fake_backend import MON1, MON2, TV, FakeBackend

from tvmode.config import Mode
from tvmode.modes import apply, current_mode, resolve

GAME = Mode("game", ["S24C570", "LG ULTRAGEAR"], "Realtek HD Audio 2nd output")
TVM = Mode("tv", ["SAMSUNG"], "Realtek Digital Output")


def test_resolve_reports_no_change_when_already_in_mode():
    b = FakeBackend()
    plan = resolve(GAME, b)
    assert [d.target for d in plan.displays] == [MON1.target, MON2.target]
    assert plan.audio.id == "id-hp"
    assert not plan.display_change_needed and not plan.audio_change_needed


def test_apply_tv_from_game():
    b = FakeBackend()
    res = apply(TVM, b)
    assert res.ok, res.errors
    assert res.display_changed and res.audio_changed
    assert b.set_display_calls == [{TV.target}]
    assert b.set_audio_calls == ["id-spk"]
    assert b.active_targets() == {TV.target}
    assert b.default_audio_id() == "id-spk"


def test_apply_game_from_tv_round_trip():
    b = FakeBackend()
    apply(TVM, b)
    res = apply(GAME, b)
    assert res.ok, res.errors
    assert b.active_targets() == {MON1.target, MON2.target}
    assert b.default_audio_id() == "id-hp"


def test_apply_is_idempotent():
    b = FakeBackend()
    res = apply(GAME, b)
    assert res.ok and not res.display_changed and not res.audio_changed
    assert b.set_display_calls == [] and b.set_audio_calls == []
    assert any("already" in m for m in res.messages)


def test_dry_run_changes_nothing():
    b = FakeBackend()
    res = apply(TVM, b, dry_run=True)
    assert res.ok
    assert b.set_display_calls == [] and b.set_audio_calls == []
    assert b.active_targets() == {MON1.target, MON2.target}
    assert any(m.startswith("would activate") for m in res.messages)
    assert any(m.startswith("would set default audio") for m in res.messages)


def test_display_failure_does_not_block_audio():
    b = FakeBackend()
    b.display_fail = RuntimeError("SetDisplayConfig failed with error 87")
    res = apply(TVM, b)
    assert not res.ok
    assert res.errors == ["display: SetDisplayConfig failed with error 87"]
    assert res.audio_changed and b.default_audio_id() == "id-spk"


def test_audio_failure_does_not_block_display():
    b = FakeBackend()
    b.audio_fail = RuntimeError("boom")
    res = apply(TVM, b)
    assert not res.ok
    assert res.display_changed and b.active_targets() == {TV.target}
    assert res.errors == ["audio: boom"]


def test_verification_failure_is_reported_after_retries():
    b = FakeBackend()
    b.display_apply_silently_ignored = True
    res = apply(TVM, b, verify_retries=3, verify_delay=0.5)
    assert not res.ok
    assert "did not take effect" in res.errors[0]
    assert b.slept == 1.5


def test_tv_unplugged_is_a_clean_error():
    b = FakeBackend()
    b.displays[2].available = False
    res = apply(TVM, b)
    assert not res.ok
    assert "no display matches 'SAMSUNG'" in res.errors[0]
    assert b.set_display_calls == [] and b.set_audio_calls == []


def test_ambiguous_matcher_is_a_clean_error():
    b = FakeBackend()
    res = apply(
        Mode("x", ["Realtek"], None), b
    )  # no display matches; use audio ambiguity
    res = apply(Mode("x", [], "Realtek"), b)
    assert not res.ok and "ambiguous" in res.errors[0]


def test_display_only_and_audio_only():
    b = FakeBackend()
    res = apply(TVM, b, do_audio=False)
    assert res.ok and res.display_changed and not res.audio_changed
    assert b.default_audio_id() == "id-hp"
    res = apply(TVM, b, do_display=False)
    assert res.ok and res.audio_changed


def test_current_mode_detection():
    b = FakeBackend()
    modes = {"game": GAME, "tv": TVM}
    assert current_mode(modes, b) == "game"
    apply(TVM, b)
    assert current_mode(modes, b) == "tv"
    # Mixed state: tv display but headphone audio -> no mode matches.
    b.set_default_audio("id-hp")
    assert current_mode(modes, b) is None
