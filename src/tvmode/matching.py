"""Resolve human-written matchers to concrete devices."""

from __future__ import annotations

from collections.abc import Callable, Iterable


class MatchError(LookupError):
    pass


class DeviceMissing(MatchError):
    """Nothing matched: the device is unplugged, off, or not detected yet."""


def match_one[T](
    matcher: str,
    candidates: Iterable[T],
    keys: Callable[[T], Iterable[str]],
    label: Callable[[T], str] = str,
    kind: str = "device",
) -> T:
    """Return the single candidate matching ``matcher``.

    Rules (all case-insensitive):
      1. If exactly one candidate has a key *equal* to the matcher, it wins.
      2. Otherwise, exactly one candidate must have a key *containing* it.
    Raises ``MatchError`` on zero or multiple matches.
    """
    m = matcher.strip().lower()
    if not m:
        raise MatchError(f"empty {kind} matcher")
    cands = list(candidates)

    exact = [c for c in cands if any(k.lower() == m for k in keys(c) if k)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        names = ", ".join(label(c) for c in exact)
        raise MatchError(
            f"{kind} matcher {matcher!r} matches several devices exactly: {names}"
        )

    partial = [c for c in cands if any(m in k.lower() for k in keys(c) if k)]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        available = ", ".join(label(c) for c in cands) or "(none)"
        raise DeviceMissing(f"no {kind} matches {matcher!r}; available: {available}")
    names = ", ".join(label(c) for c in partial)
    raise MatchError(f"{kind} matcher {matcher!r} is ambiguous; matches: {names}")
