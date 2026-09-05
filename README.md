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
- Every switch is verified after it is applied, and each half is independent:
  if the TV is unplugged the audio still switches and you get a clear error.

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
uv run tvmode status
```

`tvmode apply <mode> --dry-run` shows what would change without doing it.

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
