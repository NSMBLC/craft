"""Verdicts are computed, not chosen (Journey 6).

Evidence file (JSON or YAML) shapes accepted:
  {"metric": "acc_gain", "values": [..per-seed..], "seeds": [...], "data_id": "...", "unit": "..."}
  {"metric": "acc_gain", "value": 1.4, "ci": [1.2, 1.6], "n": 5, ...}
  {"metrics": {"acc_gain": {...as above...}, "other": {...}}, "seeds": [...], "data_id": "..."}
Uncertainty is mandatory: either `values` (>=2) or `ci`.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from ..util import CraftError, read_json, read_yaml

# two-sided 95% t critical values by degrees of freedom (1..30); beyond -> 1.96
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160,
        2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
        2.052, 2.048, 2.045, 2.042]


def t95(df: int) -> float:
    if df < 1:
        return float("inf")
    return _T95[df - 1] if df <= len(_T95) else 1.96


@dataclass
class Measurement:
    metric: str
    point: float
    ci_low: float
    ci_high: float
    n: int | None
    seeds: list | None
    data_id: str | None
    unit: str | None
    source: str  # "values" | "ci"


def load_evidence(path: Path) -> dict:
    if path.suffix.lower() in (".yaml", ".yml"):
        data = read_yaml(path, None)
    else:
        data = read_json(path, None)
    if not isinstance(data, dict):
        raise CraftError(f"evidence file {path} is not a JSON/YAML mapping")
    return data


def extract(data: dict, metric: str) -> Measurement:
    block = None
    if isinstance(data.get("metrics"), dict) and metric in data["metrics"]:
        block = dict(data["metrics"][metric])
        for k in ("seeds", "data_id", "unit"):
            block.setdefault(k, data.get(k))
    elif data.get("metric") == metric:
        block = data
    if block is None:
        raise CraftError(f"metric '{metric}' not found in evidence file")
    seeds = block.get("seeds")
    data_id = block.get("data_id")
    unit = block.get("unit")
    if isinstance(block.get("values"), list) and len(block["values"]) >= 2:
        vals = [float(x) for x in block["values"]]
        n = len(vals)
        mean = statistics.fmean(vals)
        sd = statistics.stdev(vals)
        half = t95(n - 1) * sd / math.sqrt(n)
        return Measurement(metric, mean, mean - half, mean + half, n, seeds, data_id, unit, "values")
    if block.get("value") is not None and isinstance(block.get("ci"), (list, tuple)) and len(block["ci"]) == 2:
        lo, hi = float(block["ci"][0]), float(block["ci"][1])
        return Measurement(metric, float(block["value"]), min(lo, hi), max(lo, hi), block.get("n"), seeds, data_id, unit, "ci")
    raise CraftError(
        f"metric '{metric}' has no uncertainty: provide `values` (>=2 per-seed numbers) or `value` + `ci`. "
        "A verdict without uncertainty is not auditable."
    )


def compare(op: str, x: float, threshold: float) -> bool:
    return {
        "<": x < threshold, "<=": x <= threshold, ">": x > threshold, ">=": x >= threshold,
        "==": math.isclose(x, threshold), "!=": not math.isclose(x, threshold),
    }[op]


def label_for(m: Measurement, op: str, threshold: float) -> tuple[str, str]:
    """Return (label, rationale). Mechanical outcome rule:
    supported   — the whole 95% interval meets the criterion;
    refuted     — the whole interval fails it;
    inconclusive — the interval spans the threshold."""
    point_ok = compare(op, m.point, threshold)
    lo_ok = compare(op, m.ci_low, threshold)
    hi_ok = compare(op, m.ci_high, threshold)
    if op in ("==", "!="):
        # equality criteria: decide on the point estimate, note the interval
        return ("supported" if point_ok else "refuted", "point estimate compared for equality criterion")
    if lo_ok and hi_ok:
        return ("supported", f"entire 95% interval [{m.ci_low:.4g}, {m.ci_high:.4g}] satisfies {op} {threshold}")
    if not lo_ok and not hi_ok:
        return ("refuted", f"entire 95% interval [{m.ci_low:.4g}, {m.ci_high:.4g}] fails {op} {threshold}")
    return ("inconclusive", f"95% interval [{m.ci_low:.4g}, {m.ci_high:.4g}] spans the threshold {threshold}")


def render_verdict(fm: dict, body_lines: list[str]) -> str:
    import yaml

    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n" + "\n".join(body_lines) + "\n"
