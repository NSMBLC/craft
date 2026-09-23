"""Freezing: chmod 444 + recorded sha256, and integrity verification."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .util import CraftError, sha256_file


def freeze_file(path: Path) -> str:
    if not path.exists():
        raise CraftError(f"cannot freeze {path}: file does not exist")
    digest = sha256_file(path)
    path.chmod(0o444)
    return digest


def thaw_file(path: Path) -> None:
    if path.exists():
        path.chmod(0o644)


def freeze_tree(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            p = Path(dirpath) / f
            if not p.is_symlink():
                p.chmod(0o444)
    # directories read-only last so we can still traverse
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        Path(dirpath).chmod(0o555)


def is_read_only(path: Path) -> bool:
    mode = path.stat().st_mode
    return not (mode & stat.S_IWUSR or mode & stat.S_IWGRP or mode & stat.S_IWOTH)


def check_hash(path: Path, expected: str | None) -> str | None:
    """Return None if intact, else a human-readable problem."""
    if expected is None:
        return None
    if not path.exists():
        return f"{path.name} is frozen but missing"
    actual = sha256_file(path)
    if actual != expected:
        return f"{path.name} was modified after freezing (sha256 {actual[:12]} != {expected[:12]})"
    if not is_read_only(path):
        return f"{path.name} is frozen but writable (permissions were changed)"
    return None
