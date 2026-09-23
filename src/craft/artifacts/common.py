"""Validation results shared by all artifact validators."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    field: str
    problem: str
    severity: str = "error"  # error | warning


@dataclass
class Validation:
    artifact: str
    findings: list[Finding] = field(default_factory=list)

    def error(self, field_: str, problem: str) -> None:
        self.findings.append(Finding(field_, problem, "error"))

    def warn(self, field_: str, problem: str) -> None:
        self.findings.append(Finding(field_, problem, "warning"))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        if not self.findings:
            return f"{self.artifact}: valid (all required elements present)."
        lines = [f"{self.artifact}: {'valid with notes' if self.ok else 'INCOMPLETE'}"]
        for f in self.findings:
            lines.append(f"  [{f.severity}] {f.field}: {f.problem}")
        if not self.ok:
            lines.append("  The document is not complete; fix the items above (the validator never rewrites it).")
        return "\n".join(lines)


def nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


WEAK_PHRASES = (
    "good to know",
    "would be interesting",
    "nice to know",
    "the community",
    "anyone",
    "everyone",
    "people",
    "researchers in general",
    "tbd",
    "todo",
    "n/a",
)


def looks_weak(text: str) -> str | None:
    low = (text or "").lower()
    for w in WEAK_PHRASES:
        if w in low:
            return w
    return None
