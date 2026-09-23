"""Opt-in: runs the real referee (`claude -p`). CRAFT_REAL_REFEREE=1 uv run pytest -k real_referee -s"""

from __future__ import annotations

import json
import os

import pytest

from .test_arc import HYP_FIXED_O2, HYP_TWO_RIVALS, PROBLEM_OK
from ..conftest import Craft

pytestmark = pytest.mark.skipif(os.environ.get("CRAFT_REAL_REFEREE") != "1", reason="set CRAFT_REAL_REFEREE=1")

# Planted flaw: the method gets a 40-trial tuning sweep, the baseline runs at defaults.
HYP_PLANTED = HYP_TWO_RIVALS.replace(
    "    conditions: 5 seeds, inputs >= 1e6 tokens, 2026 corpus snapshot\n",
    "    conditions: 5 seeds, inputs >= 1e6 tokens, 2026 corpus snapshot; method A tuned with a 40-trial Bayesian sweep, baseline B run at its published defaults\n",
).replace(
    "  - explanation: A benefits from more tuning attention than B\n    discriminator: equal tuning budget for both arms\n",
    "  - explanation: the evaluation slice happens to favour dense retrievers\n    discriminator: report per-domain breakdown\n",
)


def _setup(programme: Craft, hyp: str) -> None:
    assert programme("new", "inv-001", "--topic", "method A vs baseline B on large inputs").code == 0
    programme.write("investigations/inv-001/problem.md", PROBLEM_OK.replace(
        "memory_acknowledgements:\n  - ref: R-0001\n    entry: method A's accuracy advantage over baseline B holds on inputs larger than 1e6 tokens\n    justification: the new 2026 corpus has 10x longer documents so the 2025 refutation on short-document data does not apply\n",
        "memory_acknowledgements: []\n"))
    assert programme("approve", "problem", human=True).code == 0
    programme.write("investigations/inv-001/hypothesis.md", hyp)
    assert programme("validate", "hypothesis").code == 0


@pytest.mark.checkpoint("4.2")
def test_real_referee_finds_planted_tuning_asymmetry(programme: Craft):
    _setup(programme, HYP_PLANTED)
    r = programme("review", env={"CRAFT_REFEREE_BACKEND": "claude"})
    print(r.text)
    assert r.code == 0, r.text
    data = json.loads((programme.root / "investigations" / "inv-001" / "review" / "round-1.json").read_text())
    blocking = [o for o in data["objections"] if o["severity"] == "blocking"]
    assert blocking, "a sound-looking design with an obvious tuning asymmetry must draw a blocking objection"
    text = " ".join(o["statement"].lower() + " " + o["adequate_answer"].lower() for o in blocking)
    assert "tun" in text or "budget" in text or "default" in text
    from craft.artifacts.review import check_round1
    assert check_round1(data) == []


@pytest.mark.checkpoint("4.7")
def test_real_referee_does_not_invent_problems(programme: Craft):
    _setup(programme, HYP_FIXED_O2)
    r = programme("review", env={"CRAFT_REFEREE_BACKEND": "claude"})
    print(r.text)
    assert r.code == 0, r.text
    data = json.loads((programme.root / "investigations" / "inv-001" / "review" / "round-1.json").read_text())
    blocking = [o for o in data["objections"] if o["severity"] == "blocking"]
    # a sound design may still draw a blocking note from a strict referee; record it, but the
    # referee must be able to say "no blocking objections" when it finds none
    print("blocking:", [o["statement"] for o in blocking])
    assert data["no_blocking_objections"] == (len(blocking) == 0)
