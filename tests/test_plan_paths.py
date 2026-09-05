import pytest

from tvmode.display import PathRecord, PlanError, plan_paths

A = 1  # adapter luid
MON1, MON2, TV = (A, 100), (A, 101), (A, 102)
S0, S1, S2 = (A, 0), (A, 1), (A, 2)


def rec(i, src, tgt, active=False, available=True):
    return PathRecord(index=i, source=src, target=tgt, active=active, available=available)


def all_paths(active_pairs=(), unavailable=()):
    """Every source x target combination, like QDC_ALL_PATHS returns."""
    recs = []
    i = 0
    for tgt in (MON1, MON2, TV):
        for src in (S0, S1, S2):
            recs.append(
                rec(i, src, tgt, active=(src, tgt) in active_pairs, available=tgt not in unavailable)
            )
            i += 1
    return recs


def chosen_pairs(recs, idx):
    return {(r.source, r.target) for r in recs if r.index in idx}


def test_keeps_currently_active_paths_for_wanted_targets():
    recs = all_paths(active_pairs={(S0, MON1), (S1, MON2)})
    idx = plan_paths(recs, {MON1, MON2})
    assert chosen_pairs(recs, idx) == {(S0, MON1), (S1, MON2)}


def test_switch_from_monitors_to_tv_uses_a_free_source():
    recs = all_paths(active_pairs={(S0, MON1), (S1, MON2)})
    idx = plan_paths(recs, {TV})
    pairs = chosen_pairs(recs, idx)
    assert len(pairs) == 1
    (src, tgt), = pairs
    assert tgt == TV


def test_switch_from_tv_to_monitors_assigns_distinct_sources():
    recs = all_paths(active_pairs={(S0, TV)})
    idx = plan_paths(recs, {MON1, MON2})
    pairs = chosen_pairs(recs, idx)
    assert {t for _, t in pairs} == {MON1, MON2}
    srcs = [s for s, _ in pairs]
    assert len(set(srcs)) == 2, "each target must be driven by its own source"


def test_partial_overlap_keeps_existing_and_adds_new():
    recs = all_paths(active_pairs={(S0, MON1)})
    idx = plan_paths(recs, {MON1, TV})
    pairs = chosen_pairs(recs, idx)
    assert (S0, MON1) in pairs
    assert any(t == TV and s != S0 for s, t in pairs)


def test_unavailable_target_is_rejected():
    recs = all_paths(active_pairs={(S0, MON1)}, unavailable={TV})
    with pytest.raises(PlanError, match="not connected"):
        plan_paths(recs, {TV})


def test_unknown_target_is_rejected():
    recs = all_paths()
    with pytest.raises(PlanError, match="no display paths"):
        plan_paths(recs, {(A, 999)})


def test_empty_wanted_is_rejected():
    with pytest.raises(PlanError, match="zero"):
        plan_paths(all_paths(), set())


def test_not_enough_sources_is_rejected():
    # Only one source exists for both targets.
    recs = [rec(0, S0, MON1), rec(1, S0, MON2)]
    with pytest.raises(PlanError, match="free source"):
        plan_paths(recs, {MON1, MON2})


def test_deterministic():
    recs = all_paths()
    assert plan_paths(recs, {MON1, MON2}) == plan_paths(recs, {MON2, MON1})
