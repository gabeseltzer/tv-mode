import pytest

from tvmode.matching import MatchError, match_one


def keys(x):
    return x


def test_exact_match_beats_substring():
    cands = [("LG",), ("LG ULTRAGEAR",)]
    assert match_one("lg", cands, keys) == ("LG",)


def test_substring_unique():
    cands = [("S24C570",), ("LG ULTRAGEAR",)]
    assert match_one("ultra", cands, keys) == ("LG ULTRAGEAR",)


def test_matches_any_key():
    cands = [
        ("Generic PnP", r"\\?\DISPLAY#SAM0D3B#..."),
        ("LG", r"\\?\DISPLAY#GSM5B7F"),
    ]
    assert match_one("SAM0D3B", cands, keys)[0] == "Generic PnP"


def test_ambiguous_raises():
    cands = [("SAMSUNG TV",), ("SAMSUNG Monitor",)]
    with pytest.raises(MatchError, match="ambiguous"):
        match_one("samsung", cands, keys)


def test_no_match_lists_available():
    cands = [("A",), ("B",)]
    with pytest.raises(MatchError, match="available: A, B"):
        match_one("zzz", cands, keys, label=lambda c: c[0])


def test_empty_matcher():
    with pytest.raises(MatchError):
        match_one("  ", [("A",)], keys)


def test_empty_keys_are_ignored():
    cands = [("", ""), ("X", "")]
    assert match_one("x", cands, keys) == ("X", "")
