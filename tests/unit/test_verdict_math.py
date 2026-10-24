import pytest

from craft.util import CraftError

from craft.artifacts.verdict import Measurement, extract, label_for


def m(point, lo, hi):
    return Measurement("x", point, lo, hi, 5, [1], "d", None, "ci")


def test_labels():
    assert label_for(m(1.4, 1.38, 1.42), ">=", 1.5)[0] == "refuted"
    assert label_for(m(1.9, 1.7, 2.1), ">=", 1.5)[0] == "supported"
    assert label_for(m(1.5, 1.3, 1.7), ">=", 1.5)[0] == "inconclusive"
    assert label_for(m(0.1, 0.05, 0.15), "<", 0.2)[0] == "supported"


def test_extract_values_ci():
    d = {"metric": "g", "values": [1.38, 1.42, 1.40, 1.41, 1.39], "seeds": [1, 2, 3, 4, 5], "data_id": "ds"}
    r = extract(d, "g")
    assert abs(r.point - 1.40) < 1e-9 and r.ci_low < 1.40 < r.ci_high and r.n == 5


def test_extract_requires_uncertainty():
    from craft.util import CraftError
    with pytest.raises(CraftError):
        extract({"metric": "g", "value": 1.4}, "g")


def test_extract_nested_metrics():
    d = {"metrics": {"a": {"value": 2.0, "ci": [1.9, 2.1]}}, "seeds": [7], "data_id": "x"}
    r = extract(d, "a")
    assert r.seeds == [7] and r.data_id == "x"


def test_extract_flat_shape():
    d = {"pilot_cv_total_time": 1.3086, "pilot_cv_total_time_ci95": [1.1, 1.5], "other": 3}
    r = extract(d, "pilot_cv_total_time")
    assert abs(r.point - 1.3086) < 1e-9 and r.ci_low == 1.1 and r.ci_high == 1.5 and r.seeds is None
    r2 = extract({"m_values": [1.0, 1.2, 1.1], "seeds": [1, 2, 3], "data_id": "d"}, "m")
    assert r2.n == 3 and r2.seeds == [1, 2, 3]
    with pytest.raises(CraftError):
        extract({"pilot_cv_total_time": 1.3}, "pilot_cv_total_time")  # no uncertainty
