import pytest

from tvmode.cli import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, main

from fake_backend import FakeBackend, MON1, MON2, TV

CONFIG = """
[modes.game]
displays = ["S24C570", "LG ULTRAGEAR"]
audio = "Realtek HD Audio 2nd output"

[modes.tv]
displays = ["SAMSUNG"]
audio = "Realtek Digital Output"
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(CONFIG, encoding="utf-8")
    return p


def run(argv, backend, cfg=None):
    args = ["--config", str(cfg)] + argv if cfg else argv
    return main(args, backend=backend)


def test_apply_tv(cfg, capsys):
    b = FakeBackend()
    assert run(["apply", "tv"], b, cfg) == EXIT_OK
    assert b.active_targets() == {TV.target}
    out = capsys.readouterr().out
    assert "displays -> SAMSUNG" in out and "audio -> Realtek Digital Output" in out


def test_apply_unknown_mode(cfg, capsys):
    assert run(["apply", "couch"], FakeBackend(), cfg) == EXIT_CONFIG
    assert "unknown mode 'couch'" in capsys.readouterr().err


def test_apply_failure_exit_code(cfg, capsys):
    b = FakeBackend()
    b.display_fail = RuntimeError("nope")
    assert run(["apply", "tv"], b, cfg) == EXIT_FAILED
    assert "ERROR: display: nope" in capsys.readouterr().err


def test_toggle_flips_between_two_modes(cfg):
    b = FakeBackend()
    assert run(["toggle"], b, cfg) == EXIT_OK
    assert b.active_targets() == {TV.target}
    assert run(["toggle"], b, cfg) == EXIT_OK
    assert b.active_targets() == {MON1.target, MON2.target}


def test_toggle_from_unknown_state_goes_to_first_mode(cfg):
    b = FakeBackend()
    b.set_default_audio("id-cable")  # neither mode matches now
    assert run(["toggle"], b, cfg) == EXIT_OK
    assert b.default_audio_id() == "id-hp"  # first mode is game


def test_toggle_requires_two_modes(tmp_path, capsys):
    p = tmp_path / "c.toml"
    p.write_text('[modes.a]\naudio="x"\n[modes.b]\naudio="y"\n[modes.c]\naudio="z"\n')
    assert run(["toggle"], FakeBackend(), p) == EXIT_CONFIG
    assert "exactly two modes" in capsys.readouterr().err


def test_status(cfg, capsys):
    assert run(["status"], FakeBackend(), cfg) == EXIT_OK
    out = capsys.readouterr().out
    assert "current mode:    game" in out


def test_missing_config(tmp_path, capsys):
    assert run(["status"], FakeBackend(), tmp_path / "nope.toml") == EXIT_CONFIG
    assert "tvmode init" in capsys.readouterr().err


def test_init_writes_usable_config(tmp_path, capsys):
    p = tmp_path / "new.toml"
    assert run(["init"], FakeBackend(), p) == EXIT_OK
    assert p.exists()
    # Second run refuses without --force
    assert run(["init"], FakeBackend(), p) == EXIT_CONFIG
    assert run(["init", "--force"], FakeBackend(), p) == EXIT_OK
    # The generated config applies cleanly.
    b = FakeBackend()
    assert run(["apply", "tv"], b, p) == EXIT_OK
    assert b.active_targets() == {TV.target} and b.default_audio_id() == "id-spk"
