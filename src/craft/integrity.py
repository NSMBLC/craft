"""Integrity by hashes, not file permissions.

File modes do not survive git (only the exec bit is tracked), so CRAFT never changes them.
Files that record what happened (reviews, registered snapshots, verdicts, the evidence a verdict
cites, env.lock) are hashed into state.json when `craft` writes them; any later change is
detected by `craft verify` and puts the investigation on integrity hold.
"""

from __future__ import annotations

import os
from pathlib import Path

from .util import sha256_file


def make_writable(path: Path) -> None:
    """Undo the read-only mode CRAFT v1 used to set, so `craft` itself can rewrite the file."""
    if path.exists() and not os.access(path, os.W_OK):
        path.chmod(0o644)


def check_hash(path: Path, expected: str | None, label: str | None = None) -> str | None:
    """Return None if intact, else a human-readable problem."""
    if expected is None:
        return None
    name = label or path.name
    if not path.exists():
        return f"{name} is a recorded file but is missing"
    actual = sha256_file(path)
    if actual != expected:
        return f"{name} was modified outside `craft` (sha256 {actual[:12]} != recorded {expected[:12]})"
    return None
