import statistics as stdlib

import pytest

from hotpath.benchmark.statistics import bootstrap_ci, compare, describe


def test_describe_basic_statistics():
    values = [72.0, 70.0, 75.0, 68.0, 71.0, 74.0, 69.0, 73.0, 70.5, 72.5]

    d = describe(values)

    assert d.n == 10
    assert d.median == stdlib.median(values)
    assert d.mean == pytest.approx(stdlib.mean(values))
    assert d.stdev == pytest.approx(stdlib.stdev(values))
    assert d.ci_low <= d.median <= d.ci_high
    assert d.confidence == 0.95


def test_bootstrap_ci_is_deterministic_for_a_seed():
    values = [400.0, 410.0, 425.0, 430.0, 441.0, 405.0, 418.0, 433.0, 427.0, 412.0]

    assert bootstrap_ci(values, seed=1) == bootstrap_ci(values, seed=1)


def test_bootstrap_ci_narrows_with_less_spread():
    tight = [100.0, 101.0, 99.0, 100.5, 99.5, 100.2, 99.8, 100.1, 99.9, 100.0]
    wide = [60.0, 140.0, 80.0, 120.0, 100.0, 70.0, 130.0, 90.0, 110.0, 100.0]

    tight_lo, tight_hi = bootstrap_ci(tight)
    wide_lo, wide_hi = bootstrap_ci(wide)

    assert (tight_hi - tight_lo) < (wide_hi - wide_lo)


def test_single_value_has_degenerate_interval():
    d = describe([42.0])

    assert (d.median, d.ci_low, d.ci_high, d.stdev) == (42.0, 42.0, 42.0, 0.0)


def test_describe_rejects_empty():
    with pytest.raises(ValueError):
        describe([])


def test_compare_reports_change_and_separation():
    baseline = describe([423.0, 406.0, 441.0, 430.0, 415.0, 428.0, 419.0, 437.0, 410.0, 425.0])
    patched = describe([72.0, 68.0, 76.0, 71.0, 74.0, 70.0, 73.0, 69.0, 75.0, 72.0])

    c = compare(baseline, patched)

    assert c.median_change_pct == pytest.approx((patched.median - baseline.median) / baseline.median * 100, abs=0.1)
    assert c.separated is True


def test_compare_overlapping_intervals_are_not_separated():
    a = describe([100.0, 110.0, 90.0, 105.0, 95.0])
    b = describe([102.0, 108.0, 92.0, 104.0, 97.0])

    assert compare(a, b).separated is False
