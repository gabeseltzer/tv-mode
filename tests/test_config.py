import pytest

from tvmode.config import ConfigError, parse_config, render_template

GOOD = """
[modes.game]
displays = ["S24C570", "LG ULTRAGEAR"]
audio = "Realtek HD Audio 2nd output"

[modes.tv]
displays = ["SAMSUNG"]
audio = "Realtek Digital Output"
"""


def test_parse_good():
    cfg = parse_config(GOOD)
    assert set(cfg.modes) == {"game", "tv"}
    assert cfg.mode("tv").displays == ["SAMSUNG"]
    assert cfg.mode("game").audio == "Realtek HD Audio 2nd output"


def test_single_string_display_is_promoted_to_list():
    cfg = parse_config('[modes.x]\ndisplays = "TV"\n')
    assert cfg.mode("x").displays == ["TV"]


def test_audio_only_mode_ok():
    cfg = parse_config('[modes.x]\naudio = "Speakers"\n')
    assert cfg.mode("x").displays == [] and cfg.mode("x").audio == "Speakers"


@pytest.mark.parametrize(
    "text,msg",
    [
        ("", "at least one"),
        ("[other]\nx=1\n", "at least one"),
        ("[modes.x]\n", "displays and/or audio"),
        ("[modes.x]\ndisplays = [1]\n", "non-empty strings"),
        ("[modes.x]\ndisplays = [\"\"]\n", "non-empty strings"),
        ("[modes.x]\naudio = 3\n", "non-empty string"),
        ("[modes.x]\naudio = \"a\"\nbogus = 1\n", "unknown keys"),
        ("not toml [[[", "invalid TOML"),
    ],
)
def test_parse_errors(text, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(text)


def test_unknown_mode():
    cfg = parse_config(GOOD)
    with pytest.raises(ConfigError, match="unknown mode 'couch'.*game, tv"):
        cfg.mode("couch")


def test_template_round_trips():
    text = render_template(
        displays=[("S24C570", True), ("LG ULTRAGEAR", True), ("SAMSUNG", False)],
        audio=[("Realtek HD Audio 2nd output", True), ("Realtek Digital Output", False)],
    )
    cfg = parse_config(text)
    assert cfg.mode("game").displays == ["S24C570", "LG ULTRAGEAR"]
    assert cfg.mode("game").audio == "Realtek HD Audio 2nd output"
    assert cfg.mode("tv").displays == ["SAMSUNG"]
    assert cfg.mode("tv").audio == "Realtek Digital Output"


def test_template_escapes_quotes_and_backslashes():
    text = render_template(displays=[('Weird "name" \\ x', True)], audio=[])
    assert parse_config(text).mode("game").displays == ['Weird "name" \\ x']
