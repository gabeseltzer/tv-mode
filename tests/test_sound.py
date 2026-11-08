import io
import struct
import wave

from tvmode.config import parse_config
from tvmode.sound import LEAD_SILENCE, PEAK, RATE, builtin, default_for


def _samples(data: bytes) -> list[int]:
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
        raw = w.readframes(w.getnframes())
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def test_builtin_chimes_are_valid_wavs_with_lead_silence():
    for name in ("rising", "falling", "chime", "RISING"):
        s = _samples(builtin(name))
        lead = int(LEAD_SILENCE * RATE)
        assert not any(s[:lead])  # silence for the receiver to lock on
        assert max(map(abs, s)) <= PEAK * 32767 + 1
        assert max(map(abs, s)) > PEAK * 32767 * 0.9
        assert len(s) / RATE < 1.5  # short


def test_rising_and_falling_differ():
    assert builtin("rising") != builtin("falling")


def test_unknown_name_is_not_builtin():
    assert builtin("SystemNotification") is None
    assert builtin(r"C:\media\x.wav") is None


def test_default_by_mode_position():
    assert [default_for(i) for i in range(4)] == ["rising", "falling", "chime", "chime"]
    cfg = parse_config(
        "[modes.a]\naudio='x'\n[modes.b]\naudio='y'\n[modes.c]\naudio='z'\nsound=true\n"
    )
    assert [cfg.sound_for(m) for m in "abc"] == ["rising", "falling", "chime"]
