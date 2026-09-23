"""Small shared helpers: hashing, frontmatter, yaml/json IO, time."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class CraftError(Exception):
    """A rule refused something. The message is what the researcher/agent sees."""

    exit_code = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Missing frontmatter -> ({}, text)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:  # pragma: no cover - surfaced to user
        raise CraftError(f"frontmatter is not valid YAML: {e}") from e
    if not isinstance(fm, dict):
        raise CraftError("frontmatter must be a YAML mapping")
    return fm, m.group(2)


def join_frontmatter(fm: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n" + body


def read_doc(path: Path) -> tuple[dict, str]:
    if not path.exists():
        raise CraftError(f"{path} does not exist")
    return split_frontmatter(path.read_text(encoding="utf-8"))


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
