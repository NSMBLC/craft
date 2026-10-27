"""CRAFT: disciplined computational research inside a GenAI session."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("craft-research")  # single source: pyproject.toml
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
