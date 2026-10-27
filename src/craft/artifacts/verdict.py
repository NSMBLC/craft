"""Verdicts are computed, not chosen (Journey 6).

Evidence file (JSON or YAML) shapes accepted:
  {"metric": "acc_gain", "values": [..per-seed..], "seeds": [...], "data_id": "...", "unit": "..."}
  {"metric": "acc_gain", "value": 1.4, "ci": [1.2, 1.6], "n": 5, ...}
  {"metrics": {"acc_gain": {...as above...}, "other": {...}}, "seeds": [...], "data_id": "..."}
  {"<metric>": 1.31, "<metric>_ci95": [1.1, 1.5]}          (flat; seeds/data_id via flags or top-level keys)
A supplied interval states how it was computed with "interval_method" (beside "ci", or at the top level; flat
shape: "<metric>_interval_method"); it must match the criterion's registered interval_method.
Uncertainty is mandatory: either `values` (>=2) or `ci`, unless the registered criterion declares
`deterministic: <why>` (exact computation on fixed inputs); then a single `value` is compared directly.
That declaration is part of the hypothesis review registers; evidence cannot declare it.
A criterion also says which number is compared with the threshold (`judged_on`: the whole interval, the point
estimate, or one end of the interval) and, when the evidence supplies its own interval, how that interval is
computed (`interval_method`); the evidence must then state the same method.
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


JUDGED_ON = ("interval", "point", "upper_bound", "lower_bound")
_BOUND_OPS = {"upper_bound": ("<", "<="), "lower_bound": (">", ">=")}


def judging_problems(c: dict) -> list[tuple[str, str]]:
    """(field, message) for a criterion whose `judged_on` / `interval_method` cannot be judged as written."""
    out = []
    jo = c.get("judged_on")
    if jo is not None and jo not in JUDGED_ON:
        out.append(("judged_on", f"must be one of {', '.join(JUDGED_ON)} (interval when left out)"))
    elif jo in _BOUND_OPS and c.get("op") not in _BOUND_OPS[jo]:
        want = " or ".join(_BOUND_OPS[jo])
        other = "lower_bound" if jo == "upper_bound" else "upper_bound"
        out.append(("judged_on", f"{jo} is judged with {want}, not {c.get('op')!r}: that pairing passes whenever "
                    f"any part of the interval does. Use op {want}, or {other}, or `interval`"))
    if "interval_method" in c:
        if c.get("deterministic"):
            out.append(("interval_method", "a deterministic criterion has no interval; remove one of the two"))
        elif not str(c.get("interval_method") or "").strip():
            out.append(("interval_method", "say how the interval is computed (e.g. \"percentile bootstrap, 10000 "
                        "resamples over seeds\"), or remove it to let CRAFT compute a t interval from per-run values"))
    return out


_OF_ALIAS = {"point": "point", "ci_low": "lower_bound", "ci_high": "upper_bound"}  # `of:`, the older kill spelling


def kill_judged_on(k: dict) -> str:
    """What a kill criterion compares: `judged_on`, or the older `of:`; the point estimate when neither is given."""
    if k.get("judged_on") is not None:
        return k["judged_on"]
    return _OF_ALIAS.get(k.get("of"), k.get("of")) if k.get("of") is not None else "point"


def kill_met(op: str, threshold: float, point: float, lo: float | None, hi: float | None,
             judged_on: str) -> tuple[bool, float | None, str]:
    """(met, the number compared, what it is) for a kill criterion, which is met or not: `interval` needs the
    whole interval to meet the condition; a bound or the point compares that one number."""
    if lo is None or hi is None or judged_on == "point":
        return compare(op, point, threshold), point, "point estimate"
    if judged_on == "interval":
        ok = compare(op, lo, threshold) and compare(op, hi, threshold)
        return ok, (hi if op in ("<", "<=") else lo), f"whole 95% interval [{lo:.4g}, {hi:.4g}]"
    x = hi if judged_on == "upper_bound" else lo
    return compare(op, x, threshold), x, f"{judged_on.replace('_', ' ')} of the 95% interval"


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


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
    interval_method: str | None = None  # how the interval was computed, as the evidence states it


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
        for k in ("seeds", "data_id", "unit", "interval_method"):
            block.setdefault(k, data.get(k))
    elif data.get("metric") == metric:
        block = data
    elif isinstance(data.get(metric), (int, float)) and not isinstance(data.get(metric), bool):
        # flat shape: {"<metric>": 1.31, "<metric>_ci95": [lo, hi]} or {"<metric>_values": [...]}
        block = {"value": data[metric], "seeds": data.get("seeds"), "data_id": data.get("data_id"), "unit": data.get(f"{metric}_unit"),
                 "interval_method": data.get(f"{metric}_interval_method") or data.get("interval_method")}
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


def _method_missing(metric: str, block: dict, method: str) -> str | None:
    """The registered interval method, checked against what the evidence reports."""
    if not (block.get("value") is not None and isinstance(block.get("ci"), (list, tuple)) and len(block["ci"]) == 2):
        return (f"interval for '{metric}': the criterion registers its interval as \"{method}\", so give \"value\" + "
                f"\"ci\" computed that way, with \"interval_method\": \"{method}\" (per-run values alone would get "
                "CRAFT's t interval, not the registered one).")
    if _norm(block.get("interval_method")) != _norm(method):
        stated = block.get("interval_method")
        return (f"interval_method for '{metric}': " + (f"the evidence says \"{stated}\"" if stated else "not stated")
                + f"; the criterion registers \"{method}\". Compute the interval as registered and state it "
                f"(\"interval_method\": \"{method}\"); a method chosen after the data cannot back the criterion.")
    return None


def missing_fields(data: dict, metric: str, seeds: list, data_ids: list, deterministic: str | None = None,
                   interval_method: str | None = None) -> list[str]:
    """Everything an evidence file still lacks before it can back a verdict, all at once."""
    out = []
    block = _block(data, metric)
    if block is None:
        out.append(_metric_missing(metric))
    elif interval_method and not deterministic:
        p = _method_missing(metric, block, interval_method)
        if p:
            out.append(p)
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
        return Measurement(metric, mean, mean - half, mean + half, n, seeds, data_id, unit, "values",
                           interval_method="t interval over per-run values")
    if block.get("value") is not None and isinstance(block.get("ci"), (list, tuple)) and len(block["ci"]) == 2:
        lo, hi = float(block["ci"][0]), float(block["ci"][1])
        return Measurement(metric, float(block["value"]), min(lo, hi), max(lo, hi), block.get("n"), seeds, data_id, unit, "ci",
                           interval_method=block.get("interval_method") or None)
    raise CraftError(_uncertainty_missing(metric))


def compare(op: str, x: float, threshold: float) -> bool:
    return {
        "<": x < threshold, "<=": x <= threshold, ">": x > threshold, ">=": x >= threshold,
        "==": math.isclose(x, threshold), "!=": not math.isclose(x, threshold),
    }[op]


def label_for(m: Measurement, op: str, threshold: float, judged_on: str | None = None) -> tuple[str, str]:
    """Return (label, rationale). Mechanical outcome rule, by what the criterion registered as judged:
    interval (default) — supported if the whole 95% interval meets the criterion, refuted if the whole
                         interval fails it, inconclusive if it spans the threshold;
    point              — the point estimate meets it or not;
    upper_bound / lower_bound — that end of the 95% interval meets it or not."""
    point_ok = compare(op, m.point, threshold)
    if m.source == "deterministic":
        verb = "satisfies" if point_ok else "fails"
        return ("supported" if point_ok else "refuted",
                f"deterministic value {m.point:.6g} ({m.deterministic}) {verb} {op} {threshold}")
    jo = judged_on or "interval"
    if jo != "interval":
        x, what = {"point": (m.point, "point estimate"), "upper_bound": (m.ci_high, "upper bound of the 95% interval"),
                   "lower_bound": (m.ci_low, "lower bound of the 95% interval")}[jo]
        ok = compare(op, x, threshold)
        return ("supported" if ok else "refuted",
                f"{what} {x:.4g} {'satisfies' if ok else 'fails'} {op} {threshold} (judged on the {what}, as registered)")
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
