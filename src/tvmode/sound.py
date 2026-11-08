"""Built-in switch chimes, synthesized in code so no sound files are needed.

Each chime is a few soft bell-like notes (sine plus a little overtone, quick
attack, exponential decay), preceded by a short silence: a receiver on an
S/PDIF or HDMI link often needs a moment to lock onto a new stream and would
otherwise swallow the first note.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from functools import cache

RATE = 44100
LEAD_SILENCE = 0.3  # seconds
NOTE_STEP = 0.11  # seconds between note onsets
NOTE_DECAY = 0.45  # seconds each note rings for
PEAK = 0.35  # of full scale; system sounds are not meant to startle

C5, E5, G5, C6 = 523.25, 659.25, 783.99, 1046.50

# name -> note frequencies in order
CHIMES: dict[str, list[float]] = {
    "rising": [C5, E5, G5],
    "falling": [G5, E5, C5],
    "chime": [E5, C6],
}


def chime_wav(notes: list[float]) -> bytes:
    """Render ``notes`` as a 16-bit mono WAV file in memory."""
    lead = int(LEAD_SILENCE * RATE)
    step = int(NOTE_STEP * RATE)
    ring = int(NOTE_DECAY * RATE)
    total = lead + step * (len(notes) - 1) + ring
    buf = [0.0] * total
    attack = int(0.005 * RATE)  # 5 ms fade-in avoids a click
    for i, f in enumerate(notes):
        start = lead + i * step
        for n in range(ring):
            t = n / RATE
            env = math.exp(-6.0 * t / NOTE_DECAY)
            if n < attack:
                env *= n / attack
            s = math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t)
            buf[start + n] += env * s
    peak = max(abs(x) for x in buf) or 1.0
    scale = PEAK * 32767 / peak
    frames = struct.pack(f"<{total}h", *(int(x * scale) for x in buf))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return out.getvalue()


@cache
def builtin(name: str) -> bytes | None:
    """WAV bytes for a built-in chime name, or None if it isn't one."""
    notes = CHIMES.get(name.lower())
    return chime_wav(notes) if notes else None


def default_for(index: int) -> str:
    """The built-in chime for the mode at ``index`` in the config: the first
    mode rises, the second falls, any others get a two-note chime."""
    return ["rising", "falling"][index] if index < 2 else "chime"
