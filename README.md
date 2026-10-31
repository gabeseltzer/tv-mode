# tvmode

> **Warning: this is a vibe-coded experiment.** Most of this code was written
> by an AI assistant (Claude) and has only been lightly tested on one machine.
> It switches your display topology and default audio device using Windows
> APIs, which can leave you staring at a black screen if something goes wrong.
> Read the code before you trust it, keep a way to recover (e.g. Win+P, or a
> second input device), and don't run it on a machine you can't afford to poke at.

Switch a Windows PC between named display + audio setups with one command.

The motivating case: a **game** mode (two desk monitors, headphones) and a
**tv** mode (only the TV, speakers), swappable from a hotkey regardless of what
state the machine is currently in.

- Displays are switched with the Windows DisplayConfig (CCD) API: the chosen
  monitors are made active and every other one is turned off, so video goes
  *only* where you asked.
- Audio is switched by setting the default playback device for all roles.
- Switching is all or nothing: display and audio both change or neither does.
  Everything is checked first (every device is connected, Windows accepts the
  display layout), and if a half fails or doesn't verify afterwards, whatever
  already changed is rolled back. If the TV is off/unplugged you get a clear
  error and your setup is untouched.

Requires Windows 10/11 and Python 3.12+. Licensed GPL-3.0-or-later.

## Quick start

```powershell
git clone https://github.com/<you>/tvmode
cd tvmode
uv sync                 # or: pip install -e .
uv run tvmode list      # see what's detected
uv run tvmode init      # write %APPDATA%\tvmode\config.toml from the detected devices
notepad $env:APPDATA\tvmode\config.toml
uv run tvmode apply tv
uv run tvmode apply game
uv run tvmode toggle    # flip between the two
uv run tvmode test tv   # switch to tv for 10s, then put everything back
uv run tvmode status
```

`tvmode apply <mode> --dry-run` shows what would change without doing it.
`tvmode test <mode> [--seconds N]` is the safe way to try a new config: it
snapshots the current displays and audio device, applies the mode, waits, and
restores the snapshot, even if the switch only half-worked or you hit Ctrl+C.

## Config

`%APPDATA%\tvmode\config.toml` (override with `--config PATH` or `TVMODE_CONFIG`):

```toml
[modes.game]
displays = ["S24C570", "LG ULTRAGEAR"]
audio = "Realtek HD Audio 2nd output"

[modes.tv]
displays = ["SAMSUNG"]
audio = "Realtek Digital Output"
```

Each string is matched case-insensitively against the device's friendly name
and its device path/id, as shown by `tvmode list`. An exact match wins;
otherwise the substring must match exactly one connected device, or you get an
error telling you what it matched.

## Automatic switching

`tvmode watch` switches modes by itself based on *which* keyboard or mouse you
touch. It uses the Windows Raw Input API, the only one that reports the source
device per event, so the keyboard at the desk and the one on the couch can
each be tied to a mode. Add an `[auto]` section to the config:

```toml
[auto]
cooldown = 30            # seconds to ignore triggers after a switch
wiggle_window = 1.5      # seconds of mouse motion considered
wiggle_distance = 300    # total travel (counts) needed in that window
wiggle_reversals = 2     # direction changes needed in that window

[auto.modes.game]
keyboards = ["VID_308F&PID_0011"]   # any key press on this keyboard -> game
mice = ["VID_3151&PID_3000"]        # a deliberate wiggle of this mouse -> game

[auto.modes.tv]
keyboards = ["VID_04D9&PID_FC40"]
```

* `tvmode inputs` lists attached keyboards and mice with their USB VID/PID.
  One physical keyboard usually appears as several devices (one per USB
  interface); a VID/PID matcher covers all of them. Matchers are compared
  against the VID/PID, the registry description, and the full device path.
* `tvmode watch --debug` logs every event with its device, which is the easy
  way to find out which VID/PID is which keyboard.
* `tvmode watch --dry-run` logs the switches it would make without making them.
* Mouse motion only counts as a trigger if, within `wiggle_window` seconds, it
  covers at least `wiggle_distance` counts *and* reverses direction at least
  `wiggle_reversals` times on one axis. Sensor drift and a bumped desk are
  one-directional and never qualify; a deliberate back-and-forth does.
* Input from devices tied to the mode already in effect is ignored, as is
  everything during the `cooldown` after a switch.
* Switching some other way (hotkey, `tvmode apply`, Win+P) is noticed: watch
  re-reads the actual mode a second after any display change and every 15
  seconds, so the other mode's devices will switch back as expected.

Run it at logon with Task Scheduler (`uv run tvmode watch`), or from a
terminal while trying it out; Ctrl+C stops it.

## Hotkeys

`tvmode.ahk` is an AutoHotkey v2 script binding Ctrl+Alt+T / G / M to
`apply tv`, `apply game`, and `toggle`. Edit the `TVMODE` line to point at
your install.

## Exit codes

| code | meaning |
| ---- | ------- |
| 0 | done (or already in that mode) |
| 1 | a switch failed or only partly applied; details on stderr |
| 2 | config or usage error |

## Development

```powershell
uv sync
uv run pytest
```

Tests run without touching real hardware: the mode engine talks to a `Backend`
protocol and the tests use an in-memory fake. The display path planner is pure
Python over plain data and is tested directly.

## Roadmap

- **Phase 1 (this):** CLI + config + AHK hotkeys.
- **Phase 2:** single-file executable and installer, tray icon with built-in
  hotkeys, and a small configurator UI so no config editing is needed.
