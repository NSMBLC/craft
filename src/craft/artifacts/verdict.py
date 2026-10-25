"""Verdicts are computed, not chosen (Journey 6).

Evidence file (JSON or YAML) shapes accepted:
  {"metric": "acc_gain", "values": [..per-seed..], "seeds": [...], "data_id": "...", "unit": "..."}
  {"metric": "acc_gain", "value": 1.4, "ci": [1.2, 1.6], "n": 5, ...}
  {"metrics": {"acc_gain": {...as above...}, "other": {...}}, "seeds": [...], "data_id": "..."}
  {"<metric>": 1.31, "<metric>_ci95": [1.1, 1.5]}          (flat; seeds/data_id via flags or top-level keys)
Uncertainty is mandatory: either `values` (>=2) or `ci`, unless the registered criterion declares
`deterministic: <why>` (exact computation on fixed inputs); then a single `value` is compared directly.
That declaration is part of the hypothesis review registers; evidence cannot declare it.
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
    source: str  # "values" | "ci" | "deterministic"
    deterministic: str | None = None  # why the metric has no spread, as registered


def load_evidence(path: Path) -> dict:
    if path.suffix.lower() in (".yaml", ".yml"):
        data = read_yaml(path, None)
    else:
        data = read_json(path, None)
    if not isinstance(data, dict):
        raise CraftError(f"evidence file {path} is not a JSON/YAML mapping")
    return data


def _block(data: dict, metric: str) -> dict | None:
    """The part of an evidence file that reports `metric`, normalised; None when absent."""
    block = None
    if isinstance(data.get("metrics"), dict) and metric in data["metrics"]:
        block = dict(data["metrics"][metric])
        for k in ("seeds", "data_id", "unit"):
            block.setdefault(k, data.get(k))
    elif data.get("metric") == metric:
        block = data
    elif isinstance(data.get(metric), (int, float)) and not isinstance(data.get(metric), bool):
        # flat shape: {"<metric>": 1.31, "<metric>_ci95": [lo, hi]} or {"<metric>_values": [...]}
        block = {"value": data[metric], "seeds": data.get("seeds"), "data_id": data.get("data_id"), "unit": data.get(f"{metric}_unit")}
        for key in (f"{metric}_ci95", f"{metric}_ci", f"{metric}_ci_95"):
            if isinstance(data.get(key), (list, tuple)) and len(data[key]) == 2:
                block["ci"] = list(data[key])
                break
        if isinstance(data.get(f"{metric}_values"), list):
            block["values"] = data[f"{metric}_values"]
        if isinstance(data.get(f"{metric}_n"), int):
            block["n"] = data[f"{metric}_n"]
    elif isinstance(data.get(f"{metric}_values"), list):
        block = {"values": data[f"{metric}_values"], "seeds": data.get("seeds"), "data_id": data.get("data_id"), "unit": None}
    return block


def _metric_missing(metric: str) -> str:
    return (f"metric '{metric}': not found — the number the criterion is judged on. Accepted shapes: "
            f"{{\"metric\": \"{metric}\", \"values\": [...]}}, {{\"metrics\": {{\"{metric}\": {{...}}}}}}, "
            f"or flat {{\"{metric}\": <number>, \"{metric}_ci95\": [lo, hi]}}")


def _uncertainty_missing(metric: str) -> str:
    return (f"uncertainty for '{metric}': missing — a verdict compares an interval with the threshold. Give `values` "
            "(>=2 per-run numbers, e.g. \"values\": [1.38, 1.42, 1.40]) or `value` + `ci` (e.g. \"value\": 1.4, "
            "\"ci\": [1.3, 1.5]). A verdict without uncertainty is not auditable. If the metric is deterministic (exact "
            "computation on fixed inputs), that is declared on the criterion (`deterministic: <why>`) before registration, "
            "never from the evidence.")


def _has_uncertainty(block: dict) -> bool:
    vals = block.get("values")
    ci = block.get("ci")
    return (isinstance(vals, list) and len(vals) >= 2) or (block.get("value") is not None and isinstance(ci, (list, tuple)) and len(ci) == 2)


def missing_fields(data: dict, metric: str, seeds: list, data_ids: list, deterministic: str | None = None) -> list[str]:
    """Everything an evidence file still lacks before it can back a verdict, all at once."""
    out = []
    block = _block(data, metric)
    if block is None:
        out.append(_metric_missing(metric))
    elif deterministic:
        if block.get("value") is None and not block.get("values"):
            out.append(f"value for '{metric}': missing — the criterion is registered as deterministic, so give the single "
                       "\"value\" it produced.")
    elif not _has_uncertainty(block):
        out.append(_uncertainty_missing(metric))
    src = block or data
    if not seeds and not src.get("seeds") and not data.get("seeds"):
        out.append("seeds: missing — which runs produced the numbers, so they can be regenerated. Put e.g. "
                   "\"seeds\": [1, 2, 3, 4, 5] (or a range, \"seeds\": \"1-200\") in the evidence file, or pass --seed. "
                   "A deterministic computation names its fixed inputs instead, e.g. \"seeds\": [\"none: exact enumeration\"].")
    if not data_ids and not src.get("data_id") and not data.get("data_id"):
        out.append("data_id: missing — which data the runs used, so a changed or re-downloaded input is noticed. Put e.g. "
                   "\"data_id\": \"prices-2026-09-snapshot\" in the evidence file (ideally an id recorded with "
                   "`craft data add`), or pass --data-id.")
    return out


def extract(data: dict, metric: str, deterministic: str | None = None) -> Measurement:
    block = _block(data, metric)
    if block is None:
        raise CraftError(_metric_missing(metric))
    seeds = block.get("seeds")
    data_id = block.get("data_id")
    unit = block.get("unit")
    if deterministic:
        vals = [float(x) for x in block["values"]] if isinstance(block.get("values"), list) and block["values"] else []
        if vals and max(vals) - min(vals) > 1e-12 * max(1.0, abs(vals[0])):
            raise CraftError(f"'{metric}' is registered as deterministic ({deterministic}) but its values vary "
                             f"({min(vals):.6g} to {max(vals):.6g}); a deterministic metric gives one value.")
        ci = block.get("ci")
        if isinstance(ci, (list, tuple)) and len(ci) == 2 and abs(float(ci[1]) - float(ci[0])) > 0:
            raise CraftError(f"'{metric}' is registered as deterministic ({deterministic}) but the evidence gives an "
                             f"interval {list(ci)}; report the single value it produced.")
        point = float(block["value"]) if block.get("value") is not None else (vals[0] if vals else None)
        if point is None:
            raise CraftError(f"'{metric}' is registered as deterministic: give the single \"value\" it produced.")
        return Measurement(metric, point, point, point, len(vals) or 1, seeds, data_id, unit, "deterministic", deterministic)
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
    raise CraftError(_uncertainty_missing(metric))


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
    if m.source == "deterministic":
        verb = "satisfies" if point_ok else "fails"
        return ("supported" if point_ok else "refuted",
                f"deterministic value {m.point:.6g} ({m.deterministic}) {verb} {op} {threshold}")
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
