"""Configuration loading for tvmode.

Config is a TOML file:

    [modes.game]
    displays = ["S24C570", "LG ULTRAGEAR"]
    audio = "Realtek HD Audio 2nd output"

    [modes.tv]
    displays = ["SAMSUNG"]
    audio = "Realtek Digital Output"

Each ``displays`` entry and the ``audio`` value is a *matcher*: a
case-insensitive string compared against the device's friendly name and its
device path / id. An exact (case-insensitive) name match wins; otherwise a
substring match must be unambiguous.

Default location: ``%APPDATA%\\tvmode\\config.toml`` (override with the
``TVMODE_CONFIG`` environment variable or ``--config``).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass
class Mode:
    name: str
    displays: list[str] = field(default_factory=list)
    audio: str | None = None


@dataclass
class Trigger:
    """Input devices whose use means the user is at the setup for ``mode``."""

    mode: str
    keyboards: list[str] = field(default_factory=list)
    mice: list[str] = field(default_factory=list)


@dataclass
class AutoConfig:
    triggers: dict[str, Trigger] = field(default_factory=dict)
    cooldown: float = 30.0
    wiggle_window: float = 1.5
    wiggle_distance: float = 300.0
    wiggle_reversals: int = 2


@dataclass
class Config:
    modes: dict[str, Mode] = field(default_factory=dict)
    path: Path | None = None
    auto: AutoConfig | None = None

    def mode(self, name: str) -> Mode:
        try:
            return self.modes[name]
        except KeyError:
            known = ", ".join(sorted(self.modes)) or "(none)"
            raise ConfigError(
                f"unknown mode {name!r}; configured modes: {known}"
            ) from None


def default_config_path() -> Path:
    env = os.environ.get("TVMODE_CONFIG")
    if env:
        return Path(env)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "tvmode" / "config.toml"


def parse_config(text: str, path: Path | None = None) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path or 'config'}: {e}") from None

    modes_raw = data.get("modes")
    if not isinstance(modes_raw, dict) or not modes_raw:
        raise ConfigError("config must contain at least one [modes.<name>] table")

    modes: dict[str, Mode] = {}
    for name, body in modes_raw.items():
        if not isinstance(body, dict):
            raise ConfigError(f"[modes.{name}] must be a table")
        displays = body.get("displays", [])
        if isinstance(displays, str):
            displays = [displays]
        if not isinstance(displays, list) or not all(
            isinstance(d, str) and d for d in displays
        ):
            raise ConfigError(
                f"[modes.{name}].displays must be a list of non-empty strings"
            )
        audio = body.get("audio")
        if audio is not None and (not isinstance(audio, str) or not audio):
            raise ConfigError(f"[modes.{name}].audio must be a non-empty string")
        if not displays and audio is None:
            raise ConfigError(f"[modes.{name}] must set displays and/or audio")
        unknown = set(body) - {"displays", "audio"}
        if unknown:
            raise ConfigError(f"[modes.{name}] has unknown keys: {sorted(unknown)}")
        modes[name] = Mode(name=name, displays=list(displays), audio=audio)

    auto = None
    if "auto" in data:
        auto = _parse_auto(data["auto"], modes)
    return Config(modes=modes, path=path, auto=auto)


def _str_list(body: dict, table: str, key: str) -> list[str]:
    v = body.get(key, [])
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        raise ConfigError(f"[{table}].{key} must be a list of non-empty strings")
    return list(v)


def _number(body: dict, table: str, key: str, default, *, integer=False):
    v = body.get(key, default)
    ok = isinstance(v, int) if integer else isinstance(v, (int, float))
    if not ok or isinstance(v, bool) or v <= 0:
        kind = "a positive integer" if integer else "a positive number"
        raise ConfigError(f"[{table}].{key} must be {kind}")
    return v


def _parse_auto(raw, modes: dict[str, Mode]) -> AutoConfig:
    if not isinstance(raw, dict):
        raise ConfigError("[auto] must be a table")
    unknown = set(raw) - {
        "modes",
        "cooldown",
        "wiggle_window",
        "wiggle_distance",
        "wiggle_reversals",
    }
    if unknown:
        raise ConfigError(f"[auto] has unknown keys: {sorted(unknown)}")

    auto = AutoConfig(
        cooldown=float(_number(raw, "auto", "cooldown", 30.0)),
        wiggle_window=float(_number(raw, "auto", "wiggle_window", 1.5)),
        wiggle_distance=float(_number(raw, "auto", "wiggle_distance", 300.0)),
        wiggle_reversals=_number(raw, "auto", "wiggle_reversals", 2, integer=True),
    )

    trig_raw = raw.get("modes")
    if not isinstance(trig_raw, dict) or not trig_raw:
        raise ConfigError("[auto] must contain at least one [auto.modes.<name>] table")
    for name, body in trig_raw.items():
        table = f"auto.modes.{name}"
        if name not in modes:
            known = ", ".join(sorted(modes))
            raise ConfigError(f"[{table}] refers to unknown mode; modes: {known}")
        if not isinstance(body, dict):
            raise ConfigError(f"[{table}] must be a table")
        unknown = set(body) - {"keyboards", "mice"}
        if unknown:
            raise ConfigError(f"[{table}] has unknown keys: {sorted(unknown)}")
        t = Trigger(
            mode=name,
            keyboards=_str_list(body, table, "keyboards"),
            mice=_str_list(body, table, "mice"),
        )
        if not t.keyboards and not t.mice:
            raise ConfigError(f"[{table}] must set keyboards and/or mice")
        auto.triggers[name] = t
    return auto


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        raise ConfigError(
            f"config file not found: {path}\nRun `tvmode init` to create one from the detected devices."
        )
    return parse_config(path.read_text(encoding="utf-8"), path)


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_template(
    displays: list[tuple[str, bool]],
    audio: list[tuple[str, bool]],
) -> str:
    """Produce a starter config.

    ``displays``/``audio`` are (label, currently_active_or_default) pairs. The
    currently active devices are put into the ``game`` mode; the ``tv`` mode is
    left as a commented list of everything else for the user to fill in.
    """
    active_disp = [d for d, on in displays if on]
    other_disp = [d for d, on in displays if not on]
    default_audio = next((a for a, on in audio if on), None)
    other_audio = [a for a, on in audio if not on]

    lines = [
        "# tvmode configuration",
        "# Each entry is matched case-insensitively against the device's name (or path/id).",
        "# Run `tvmode list` to see the devices detected on this machine.",
        "",
        "[modes.game]",
        "displays = [" + ", ".join(_toml_str(d) for d in active_disp) + "]",
    ]
    if default_audio:
        lines.append("audio = " + _toml_str(default_audio))
    else:
        lines.append('# audio = "Headphones"')
    lines += [
        "",
        "[modes.tv]",
        "# Pick the display(s) and audio device for the couch. Detected but inactive:",
    ]
    for d in other_disp:
        lines.append("#   display: " + d)
    for a in other_audio:
        lines.append("#   audio:   " + a)
    tv_disp = other_disp[:1] or ["CHANGE-ME"]
    lines.append("displays = [" + ", ".join(_toml_str(d) for d in tv_disp) + "]")
    if other_audio:
        lines.append("audio = " + _toml_str(other_audio[0]))
    else:
        lines.append('# audio = "Speakers"')
    lines.append("")
    return "\n".join(lines)
