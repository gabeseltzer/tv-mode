"""Command-line interface for tvmode.

Exit codes: 0 success, 1 a switch failed or was only partially applied,
2 configuration / usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    render_template,
)
from .modes import Backend, WindowsBackend, apply, current_mode, restore, snapshot

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2


def _out(*parts: str) -> None:
    print(*parts)


def cmd_list(args, backend: Backend) -> int:
    from . import audio as audio_mod
    from . import display as display_mod

    _out("Displays:")
    for d in display_mod.list_displays(include_phantom=args.all):
        flag = "*" if d.active else ("-" if d.available else " ")
        _out(
            f"  [{flag}] {d.label:<30} {d.output:<12} {d.gdi_name or '':<14} {d.device_path}"
        )
    _out("    * = active   - = connected but off")
    _out("")
    _out("Audio outputs:")
    for a in audio_mod.list_audio_devices(include_inactive=args.all):
        flag = "*" if a.is_default else " "
        _out(f"  [{flag}] {a.label:<50} {a.state:<12} {a.id}")
    _out("    * = default")
    return EXIT_OK


def cmd_init(args, backend: Backend) -> int:
    path: Path = args.config or default_config_path()
    if path.exists() and not args.force:
        _out(f"config already exists at {path} (use --force to overwrite)")
        return EXIT_CONFIG
    displays = [(d.label, d.active) for d in backend.list_displays() if d.available]
    default_id = backend.default_audio_id()
    audio = [(a.label, a.id == default_id) for a in backend.list_audio()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_template(displays, audio), encoding="utf-8")
    _out(f"wrote starter config to {path}")
    _out("edit the [modes.tv] section, then run: tvmode apply tv")
    return EXIT_OK


def _load(args) -> Config:
    return load_config(args.config)


def _report(res) -> int:
    for m in res.messages:
        _out(m)
    for e in res.errors:
        print("ERROR:", e, file=sys.stderr)
    return EXIT_OK if res.ok else EXIT_FAILED


def cmd_apply(args, backend: Backend) -> int:
    cfg = _load(args)
    mode = cfg.mode(args.mode)
    res = apply(
        mode,
        backend,
        do_display=not args.audio_only,
        do_audio=not args.display_only,
        dry_run=args.dry_run,
    )
    return _report(res)


def cmd_toggle(args, backend: Backend) -> int:
    cfg = _load(args)
    if args.between:
        a, b = args.between
        cfg.mode(a), cfg.mode(b)  # validate
        names = [a, b]
    else:
        names = list(cfg.modes)
        if len(names) != 2:
            raise ConfigError(
                f"toggle needs exactly two modes (have {len(names)}); use --between A B"
            )
    cur = current_mode({n: cfg.modes[n] for n in names}, backend)
    target = names[1] if cur == names[0] else names[0]
    _out(f"current: {cur or 'unknown'} -> switching to {target}")
    res = apply(cfg.mode(target), backend, dry_run=args.dry_run)
    return _report(res)


def cmd_test(args, backend: Backend) -> int:
    """Switch to a mode, hold it for a few seconds, then put everything back
    the way it was. Restoring happens even on failure or Ctrl+C."""
    cfg = _load(args)
    mode = cfg.mode(args.mode)
    do_display = not args.audio_only
    do_audio = not args.display_only
    snap = snapshot(backend)
    _out(f"current: displays={snap.display_names}; audio={snap.audio_name}")
    _out(f"testing mode {mode.name!r} for {args.seconds:g}s ...")
    rc = EXIT_OK
    try:
        res = apply(mode, backend, do_display=do_display, do_audio=do_audio)
        rc = _report(res)
        if res.display_changed or res.audio_changed:
            backend.sleep(args.seconds)
        else:
            _out("nothing changed; reverting immediately")
    except KeyboardInterrupt:
        _out("interrupted; reverting")
        rc = EXIT_FAILED
    finally:
        _out("reverting to previous setup ...")
        back = restore(snap, backend, do_display=do_display, do_audio=do_audio)
        rc = max(rc, _report(back))
    return rc


def cmd_status(args, backend: Backend) -> int:
    cfg = _load(args)
    active = {d.label for d in backend.list_displays() if d.active}
    default_id = backend.default_audio_id()
    default = next(
        (a.label for a in backend.list_audio() if a.id == default_id), default_id
    )
    _out("active displays:", ", ".join(sorted(active)) or "(none)")
    _out("default audio:  ", default or "(none)")
    _out(
        "current mode:   ",
        current_mode(cfg.modes, backend) or "(no configured mode matches)",
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tvmode",
        description="Switch Windows display topology and default audio device between named modes.",
    )
    p.add_argument("--version", action="version", version=f"tvmode {__version__}")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="path to config.toml (default: %%APPDATA%%\\tvmode\\config.toml or $TVMODE_CONFIG)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="list detected displays and audio outputs")
    s.add_argument(
        "--all", action="store_true", help="include disconnected/phantom devices"
    )
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("init", help="write a starter config from the detected devices")
    s.add_argument("--force", action="store_true", help="overwrite an existing config")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("apply", help="switch to a mode")
    s.add_argument("mode")
    s.add_argument("--dry-run", action="store_true", help="show what would change")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--display-only", action="store_true")
    g.add_argument("--audio-only", action="store_true")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("toggle", help="switch to the other mode (for a single hotkey)")
    s.add_argument("--between", nargs=2, metavar=("A", "B"))
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_toggle)

    s = sub.add_parser(
        "test", help="switch to a mode for a few seconds, then switch back"
    )
    s.add_argument("mode")
    s.add_argument(
        "--seconds",
        "-s",
        type=float,
        default=10.0,
        help="how long to hold the mode before reverting (default 10)",
    )
    g = s.add_mutually_exclusive_group()
    g.add_argument("--display-only", action="store_true")
    g.add_argument("--audio-only", action="store_true")
    s.set_defaults(func=cmd_test)

    s = sub.add_parser(
        "status", help="show current devices and which mode is in effect"
    )
    s.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None, backend: Backend | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = backend or WindowsBackend()
    try:
        return args.func(args, backend)
    except ConfigError as e:
        print("config error:", e, file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
