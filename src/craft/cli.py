"""`craft` — the one rule engine. Every gate, transition and computation lives here."""

from __future__ import annotations

import difflib
import json
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from . import envlock, hooks
from . import memory as mem
from .artifacts import review as rv
from .artifacts.closure import close_investigation
from .artifacts.hypothesis import criteria_table, validate_hypothesis
from .artifacts.literature import add_source, lint_priority_claims, load_sources, validate_literature
from .artifacts.problem import kill_criteria, validate_problem
from .artifacts.verdict import compare, extract, label_for, load_evidence, render_verdict
from .cli_support import pick_investigation, status_text, verify_all, verify_investigation
from .freeze import freeze_file, thaw_file
from .human import confirm, require_human
from .paths import DEFAULT_CONFIG, PROGRAMME_MARKER, InvestigationPaths, Programme, find_programme_root
from .referee import build_round1_prompt, build_round2_prompt, run_referee
from .state import Acknowledgement, Approval, InvestigationState, Phase, ReviewRound, VerdictRef, dump_public, new_state
from .util import CraftError, join_frontmatter, now_iso, read_doc, sha256_file, split_frontmatter, write_yaml

app = typer.Typer(help="CRAFT: disciplined computational research inside a GenAI session.", no_args_is_help=True,
                  add_completion=False)
lit_app = typer.Typer(help="Literature map (Journey 2).", no_args_is_help=True)
review_app = typer.Typer(help="Independent review rounds (Journey 4).", no_args_is_help=True)
env_app = typer.Typer(help="Locked environment (Journey 6.1).", no_args_is_help=True)
reopen_app = typer.Typer(help="Researcher-only: reopen an approved document or an exhausted review.", no_args_is_help=True)
app.add_typer(lit_app, name="lit")
app.add_typer(review_app, name="review")
app.add_typer(env_app, name="env")
app.add_typer(reopen_app, name="reopen")

INV_OPT = typer.Option(None, "--inv", help="Investigation id (defaults to the only open one).")


def echo(msg: str = "") -> None:
    typer.echo(msg)


def _prog() -> Programme:
    return Programme(find_programme_root())


def _ctx(inv_id: Optional[str]) -> tuple[Programme, InvestigationPaths, InvestigationState]:
    prog = _prog()
    inv_id = pick_investigation(prog, inv_id)
    root = prog.investigation_dir(inv_id)
    inv = InvestigationPaths(root)
    state = InvestigationState.load(root)
    _refresh(inv, state)
    return prog, inv, state


def _refresh(inv: InvestigationPaths, state: InvestigationState) -> None:
    """Derived transitions: frozen -> executing once tasks.md exists."""
    if state.phase == Phase.FROZEN and inv.tasks.exists():
        state.phase = Phase.EXECUTING
        state.save(inv.root)


def _template(name: str) -> str:
    return resources.files("craft.templates").joinpath(name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ init

@app.command()
def init(host: str = typer.Option("claude-code", help="Host adapter to install."),
         path: Path = typer.Option(Path("."), help="Programme root (default: current directory).")) -> None:
    """Turn this directory into a CRAFT programme (idempotent; never overwrites your files)."""
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = []
    marker = root / PROGRAMME_MARKER
    if not marker.exists():
        cfg = dict(DEFAULT_CONFIG)
        cfg["host"] = host
        write_yaml(marker, cfg)
        created.append(PROGRAMME_MARKER)
    prog = Programme(root)
    for d in (prog.memory_dir, prog.archive_dir, prog.investigations_dir):
        if not d.exists():
            d.mkdir(parents=True)
            created.append(d.name + "/")
    mem.ensure_memory_files(prog)
    if host == "claude-code":
        created += _install_claude_code_adapter(root)
    else:
        raise CraftError(f"no adapter for host '{host}' yet (available: claude-code)")
    echo("CRAFT programme ready at " + str(root))
    for c in created:
        echo(f"  + {c}")
    if not created:
        echo("  (nothing to do; already initialised)")
    echo("Next: open your GenAI session here. Researcher-only commands: craft approve / close / reopen / untaint.")


def _install_claude_code_adapter(root: Path) -> list[str]:
    created = []
    adapter = resources.files("craft.adapters.claude_code")
    claude_dir = root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    # settings.json: merge
    settings_path = claude_dir / "settings.json"
    ours = json.loads(adapter.joinpath("settings.json").read_text(encoding="utf-8"))
    if settings_path.exists():
        current = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        changed = _merge_settings(current, ours)
        if changed:
            settings_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            created.append(".claude/settings.json (merged CRAFT hooks and deny rules)")
    else:
        settings_path.write_text(json.dumps(ours, indent=2) + "\n", encoding="utf-8")
        created.append(".claude/settings.json")
    # CLAUDE.md: append block once
    block = adapter.joinpath("CLAUDE.md").read_text(encoding="utf-8")
    cm = root / "CLAUDE.md"
    if cm.exists():
        text = cm.read_text(encoding="utf-8")
        if "<!-- craft:begin -->" not in text:
            cm.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
            created.append("CLAUDE.md (appended CRAFT block)")
    else:
        cm.write_text(block, encoding="utf-8")
        created.append("CLAUDE.md")
    skill_dir = claude_dir / "skills" / "craft"
    skill_dir.mkdir(parents=True, exist_ok=True)
    sk = skill_dir / "SKILL.md"
    if not sk.exists():
        sk.write_text(adapter.joinpath("skills/craft/SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
        created.append(".claude/skills/craft/SKILL.md")
    return created


def _merge_settings(current: dict, ours: dict) -> bool:
    changed = False
    perms = current.setdefault("permissions", {})
    deny = perms.setdefault("deny", [])
    # Claude Code matches file rules only as Edit(path); earlier adapters also wrote Write(path)
    # rules, which trigger a warning at session start. Drop those.
    stale = [r for r in deny if r.startswith("Write(") and r.replace("Write(", "Edit(", 1) in ours["permissions"]["deny"]]
    for r in stale:
        deny.remove(r)
        changed = True
    for rule in ours["permissions"]["deny"]:
        if rule not in deny:
            deny.append(rule)
            changed = True
    allow = perms.setdefault("allow", [])
    for rule in ours["permissions"].get("allow", []):
        if rule not in allow:
            allow.append(rule)
            changed = True
    hooks_cfg = current.setdefault("hooks", {})
    for event, groups in ours["hooks"].items():
        existing = hooks_cfg.setdefault(event, [])
        for g in groups:
            present = {(eg.get("matcher"), h.get("command")) for eg in existing for h in eg.get("hooks", [])}
            if not all((g.get("matcher"), h["command"]) in present for h in g["hooks"]):
                existing.append(g)
                changed = True
    return changed


# ------------------------------------------------------------------ recall / new

@app.command()
def recall(text: str = typer.Argument(..., help="The idea, in the researcher's words.")) -> None:
    """Search programme memory (findings, refutations, open questions, archived investigations)."""
    prog = _prog()
    hits = mem.recall(prog, text)
    if not hits:
        echo("No related memory entries.")
        return
    echo(f"{len(hits)} related memory entr{'y' if len(hits) == 1 else 'ies'}:")
    for h in hits:
        echo(f"- {h.cite()}\n    overlap: {', '.join(h.overlap)}  -> {h.pointer}")
    if any(h.kind in prog.config['recall']['require_ack_kinds'] for h in hits):
        echo("Some entries must be acknowledged before a new investigation on this topic: "
             "`craft new <id> --topic ... --acknowledge <id> --justification \"what changed\"`.")


@app.command()
def new(inv_id: str = typer.Argument(..., metavar="ID"),
        topic: str = typer.Option(..., "--topic", help="The question in one line (used for recall)."),
        acknowledge: list[str] = typer.Option([], "--acknowledge", help="Memory entry id being acknowledged (repeatable)."),
        justification: list[str] = typer.Option([], "--justification", help="Why the acknowledged entry does not settle this (one per --acknowledge)."),
        lock: Optional[Path] = typer.Option(None, "--lock", help="Environment lock file to record as v1 (e.g. uv.lock).")) -> None:
    """Create an investigation. Refuses while a refuted related claim is unacknowledged."""
    prog = _prog()
    if prog.investigation_dir(inv_id).exists() or (prog.archive_dir / inv_id).exists():
        raise CraftError(f"investigation id '{inv_id}' already exists")
    if len(acknowledge) != len(justification):
        raise CraftError("give exactly one --justification per --acknowledge")
    hits = mem.collisions(prog, topic)
    missing = [h for h in hits if h.id not in set(acknowledge)]
    if missing:
        lines = ["cannot create the investigation: programme memory holds related entries that must be "
                 "acknowledged with a justification first:"]
        for h in missing:
            lines.append(f"  - {h.cite()}")
        lines.append("Cite these to the researcher, ask what has changed, then re-run with "
                     "--acknowledge <id> --justification \"...\" for each.")
        raise CraftError("\n".join(lines))
    for ref in acknowledge:
        if mem.find_entry(prog, ref) is None:
            raise CraftError(f"--acknowledge {ref}: no such memory entry")
    root = prog.investigation_dir(inv_id)
    root.mkdir(parents=True)
    inv = InvestigationPaths(root)
    state = new_state(inv_id, topic)
    acks = []
    for ref, just in zip(acknowledge, justification):
        if not just.strip() or len(just.split()) < 4:
            raise CraftError(f"--justification for {ref} is too thin; state concretely what changed")
        state.acknowledgements.append(Acknowledgement(ref=ref, justification=just, when=now_iso()))
        entry = mem.find_entry(prog, ref) or {}
        acks.append({"ref": ref, "entry": entry.get("claim") or entry.get("question", ""), "justification": just})
    import yaml
    acks_yaml = yaml.safe_dump(acks, default_flow_style=False).strip() if acks else "[]"
    if acks:
        acks_yaml = "\n" + "\n".join("  " + line for line in acks_yaml.splitlines())
    text = _template("problem.md").replace("{id}", inv_id).replace("{acks}", acks_yaml)
    inv.problem.write_text(text, encoding="utf-8")
    inv.literature_dir.mkdir()
    inv.review_dir.mkdir()
    inv.experiments_dir.mkdir()
    envlock.init_lock(inv, state, lock)
    state.save(root)
    echo(f"Created investigations/{inv_id}/ (phase: framing).")
    if acks:
        echo(f"Recorded {len(acks)} memory acknowledgement(s) in problem.md.")
    echo("Next: interview the researcher about readers and fill problem.md; `craft validate problem`; "
         "then the researcher runs `craft approve problem`.")


# ------------------------------------------------------------------ validate / lint

@app.command()
def validate(artifact: str = typer.Argument(..., help="problem | hypothesis | literature | all"),
             inv_id: Optional[str] = INV_OPT) -> None:
    """Check an artifact against its required shape. Reports; never rewrites."""
    prog, inv, state = _ctx(inv_id)
    results = []
    if artifact in ("problem", "all"):
        results.append(validate_problem(inv.problem, int(prog.config["limits"]["problem_max_words"])))
    if artifact in ("hypothesis", "all"):
        if not inv.hypothesis.exists():
            raise CraftError("hypothesis.md does not exist yet")
        results.append(validate_hypothesis(inv.hypothesis))
    if artifact in ("literature", "all"):
        results.append(validate_literature(inv.sources))
    if not results:
        raise CraftError("artifact must be problem, hypothesis, literature or all")
    for r in results:
        echo(r.render())
    if not all(r.ok for r in results):
        raise typer.Exit(code=1)


@app.command()
def lint(doc: Path = typer.Argument(..., help="Any markdown document."), inv_id: Optional[str] = INV_OPT) -> None:
    """Flag bare priority claims ('no prior work addresses this') lacking a named closest work + delta."""
    prog, inv, state = _ctx(inv_id)
    problems = lint_priority_claims(doc, inv.sources)
    if not problems:
        echo(f"{doc}: no bare priority claims.")
        return
    for p in problems:
        echo(f"- {p}")
    raise typer.Exit(code=1)


# ------------------------------------------------------------------ literature

@lit_app.command("add")
def lit_add(key: str, title: str = typer.Option(..., "--title"),
            fulltext: Optional[Path] = typer.Option(None, "--fulltext", help="Path to the full text you read."),
            abstract_only: bool = typer.Option(False, "--abstract-only"),
            reason: Optional[str] = typer.Option(None, "--reason", help="Why it was consulted and rejected."),
            claims: str = typer.Option("", "--claims"), method: str = typer.Option("", "--method"),
            relation: str = typer.Option("", "--relation", help="supports | conflicts | orthogonal | mixed"),
            does_not_cover: str = typer.Option("", "--does-not-cover"),
            inv_id: Optional[str] = INV_OPT) -> None:
    """Record a source: used (full text on disk) or consulted-and-rejected (one-line reason)."""
    prog, inv, state = _ctx(inv_id)
    if state.is_frozen:
        raise CraftError("the literature map is part of the frozen design")
    if fulltext is None and not abstract_only:
        raise CraftError("give --fulltext <path> for a source you read, or --abstract-only --reason for one you did not")
    entry = add_source(inv.sources, key, title, None if abstract_only else fulltext, reason, claims, method, relation, does_not_cover)
    echo(f"Added {key} as {entry['status']}.")


@lit_app.command("closest")
def lit_closest(key: str, delta: str = typer.Option(..., "--delta", help="One paragraph: what this adds beyond it."),
                inv_id: Optional[str] = INV_OPT) -> None:
    """Name the single closest prior work and the delta against it."""
    prog, inv, state = _ctx(inv_id)
    if state.is_frozen:
        raise CraftError("the literature map is part of the frozen design")
    data = load_sources(inv.sources)
    if key not in {s.get("key") for s in data["sources"] if s.get("status") == "used"}:
        raise CraftError(f"'{key}' is not a used source (full text read)")
    data["closest_prior_work"] = key
    data["delta"] = delta
    write_yaml(inv.sources, data)
    echo(f"closest_prior_work = {key}")


# ------------------------------------------------------------------ approve (human)

@app.command()
def approve(what: str = typer.Argument(..., help="problem"), inv_id: Optional[str] = INV_OPT,
            note: str = typer.Option("", "--note")) -> None:
    """RESEARCHER ONLY. Approve the one-page problem statement; freezes it and opens design."""
    if what != "problem":
        raise CraftError("only `craft approve problem` exists; designs are frozen by review, not approval")
    require_human("approve problem")
    prog, inv, state = _ctx(inv_id)
    state.require_untainted("approve problem")
    state.require_phase(Phase.FRAMING, action="approve problem")
    v = validate_problem(inv.problem, int(prog.config["limits"]["problem_max_words"]))
    if not v.ok:
        raise CraftError("problem.md is not complete:\n" + v.render())
    fm, body = read_doc(inv.problem)
    echo(f"Problem statement for {state.id} ({inv.problem}):")
    echo(f"  studying:   {fm.get('studying')}")
    echo(f"  to find out:{fm.get('to_find_out')}")
    echo(f"  so that:    {fm.get('so_that', {}).get('reader')} understands {fm.get('so_that', {}).get('understands')}")
    echo(f"  cost:       {fm.get('cost_of_not_answering')}")
    echo(f"  kill:       {[k.get('condition') for k in fm.get('kill_criteria', [])]}")
    if not confirm("Approve and freeze this problem statement?"):
        echo("Not approved.")
        raise typer.Exit(code=1)
    digest = freeze_file(inv.problem)
    state.problem_sha256 = digest
    state.approvals.append(Approval(what="problem", when=now_iso(), sha256=digest, note=note))
    state.attend("approve-problem", "problem.md", note)
    state.phase = Phase.DESIGNING
    if not inv.hypothesis.exists():
        inv.hypothesis.write_text(_template("hypothesis.md").replace("{id}", state.id), encoding="utf-8")
    state.save(inv.root)
    echo(f"Approved. problem.md frozen (sha256 {digest[:12]}). Phase: designing. hypothesis.md draft created.")


# ------------------------------------------------------------------ review

@review_app.command("request")
def review_request(inv_id: Optional[str] = INV_OPT) -> None:
    """Run the independent referee on the design. Freezes the hypothesis on a clean pass."""
    prog, inv, state = _ctx(inv_id)
    state.require_untainted("request review")
    state.require_phase(Phase.DESIGNING, Phase.RESPONDING, action="request review")
    limit = int(prog.config["limits"]["review_rounds"])
    n = len(state.review.rounds) + 1
    if state.review.exhausted or n > limit:
        raise CraftError(
            f"review is capped at {limit} rounds and round {limit} left blocking objections unresolved "
            f"({', '.join(state.open_blocking)}). The remaining items must be genuinely fixed, then a "
            "researcher runs `craft reopen review` to start a fresh cycle. Arguing them down is not a path."
        )
    hv = validate_hypothesis(inv.hypothesis)
    if not hv.ok:
        raise CraftError("the hypothesis is not complete enough to review:\n" + hv.render())
    if inv.sources.exists():
        lv = validate_literature(inv.sources)
        if not lv.ok:
            raise CraftError("the literature map is not complete:\n" + lv.render())
    cfg = prog.config["referee"]
    if n == 1:
        sys_p, user_p = build_round1_prompt(inv)
        data = _run_checked(cfg, sys_p, user_p, rv.ROUND1_SCHEMA, n, lambda d: rv.check_round1(d))
        objections = data.get("objections", [])
        blocking = [o["id"] for o in objections if o["severity"] == "blocking"]
        advisory = [o["id"] for o in objections if o["severity"] == "advisory"]
        rnd = ReviewRound(n=n, when=now_iso(), backend=cfg.get("backend", "claude"),
                          hypothesis_sha256=sha256_file(inv.hypothesis), objections=objections,
                          blocking_open=blocking, advisory=advisory)
    else:
        prev = state.review.rounds[-1]
        rv.ensure_responses(prev.blocking_open, prev.responses)
        round1 = json.loads(inv.review_round(1).read_text(encoding="utf-8"))
        snap = inv.review_dir / f"round-{prev.n}.hypothesis.md"
        old = snap.read_text(encoding="utf-8") if snap.exists() else ""
        diff = "".join(difflib.unified_diff(old.splitlines(True), inv.hypothesis.read_text(encoding="utf-8").splitlines(True),
                                            "hypothesis.md (round %d)" % prev.n, "hypothesis.md (now)"))
        sys_p, user_p = build_round2_prompt(inv, round1, prev.responses, diff)
        data = _run_checked(cfg, sys_p, user_p, rv.ROUND2_SCHEMA, n, lambda d: rv.check_round2(d, prev.blocking_open))
        judgements = data.get("judgements", [])
        unresolved = [j["id"] for j in judgements if j["decision"] == "unresolved" and j["id"] in prev.blocking_open]
        rnd = ReviewRound(n=n, when=now_iso(), backend=cfg.get("backend", "claude"),
                          hypothesis_sha256=sha256_file(inv.hypothesis), judgements=judgements,
                          blocking_open=unresolved, advisory=prev.advisory)
    rp = inv.review_round(n)
    if rp.exists():
        rp.chmod(0o644)
    rp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rp.chmod(0o444)
    snap = inv.review_dir / f"round-{n}.hypothesis.md"
    if snap.exists():
        snap.chmod(0o644)
    snap.write_text(inv.hypothesis.read_text(encoding="utf-8"), encoding="utf-8")
    snap.chmod(0o444)
    state.review.rounds.append(rnd)

    echo(f"Review round {n} ({rnd.backend}) written to {rp.relative_to(prog.root)}")
    if n == 1:
        for o in rnd.objections:
            echo(f"  [{o['severity']}] {o['id']} ({o['category']}) -> {o['target']['document']} § {o['target']['section']}")
            echo(f"      {o['statement']}")
            echo(f"      adequate answer: {o['adequate_answer']}")
    else:
        for j in rnd.judgements:
            echo(f"  {j['id']}: {j['decision']} — {j['reason']}")
    if not rnd.blocking_open:
        digest = freeze_file(inv.hypothesis)
        state.review.frozen_at = now_iso()
        state.review.frozen_sha256 = digest
        state.review.exhausted = False
        state.phase = Phase.FROZEN
        if inv.sources.exists():
            freeze_file(inv.sources)
        if inv.lit_map.exists():
            freeze_file(inv.lit_map)
        state.save(inv.root)
        adv = f" {len(rnd.advisory)} advisory note(s) recorded." if rnd.advisory else ""
        echo(f"No blocking objections.{adv} hypothesis.md is now FROZEN (sha256 {digest[:12]}). "
             "tasks.md may be written.")
        return
    state.phase = Phase.RESPONDING
    if n >= limit:
        state.review.exhausted = True
    state.save(inv.root)
    echo(f"{len(rnd.blocking_open)} blocking objection(s) open: {', '.join(rnd.blocking_open)}.")
    if state.review.exhausted:
        echo("Round cap reached: these must be genuinely fixed; then a researcher runs `craft reopen review`.")
    else:
        echo("Change the design, then `craft review respond <id> --pointer <doc#section> --note ...` for each, "
             "and request round 2.")


def _run_checked(cfg, sys_p, user_p, schema, n, checker) -> dict:
    data = run_referee(cfg, sys_p, user_p, schema, n)
    problems = checker(data)
    if problems:
        data = run_referee(cfg, sys_p + "\n\nYour previous output was rejected: " + "; ".join(problems), user_p, schema, n)
        problems = checker(data)
        if problems:
            raise CraftError("referee output rejected twice: " + "; ".join(problems))
    return data


@review_app.command("respond")
def review_respond(objection_id: str, pointer: str = typer.Option(..., "--pointer", help="doc#section that changed, e.g. hypothesis.md#criteria"),
                   note: str = typer.Option(..., "--note"), inv_id: Optional[str] = INV_OPT) -> None:
    """File the author's response to a blocking objection (a pointer to the design change)."""
    prog, inv, state = _ctx(inv_id)
    state.require_phase(Phase.RESPONDING, action="respond to objections")
    rnd = state.review.rounds[-1]
    if objection_id not in rnd.blocking_open:
        raise CraftError(f"{objection_id} is not an open blocking objection ({', '.join(rnd.blocking_open) or 'none'})")
    rnd.responses[objection_id] = {"pointer": pointer, "note": note, "when": now_iso()}
    rf = inv.review_responses(rnd.n)
    with rf.open("a", encoding="utf-8") as f:
        f.write(f"## {objection_id}\n\n- pointer: {pointer}\n- note: {note}\n- when: {now_iso()}\n\n")
    state.save(inv.root)
    remaining = [i for i in rnd.blocking_open if i not in rnd.responses]
    echo(f"Response to {objection_id} filed. Remaining unanswered: {', '.join(remaining) or 'none'}.")


@review_app.command("show")
def review_show(inv_id: Optional[str] = INV_OPT) -> None:
    """Print the review rounds and their status."""
    prog, inv, state = _ctx(inv_id)
    if not state.review.rounds:
        echo("No review rounds yet.")
        return
    for r in state.review.rounds:
        echo(f"Round {r.n} ({r.when}) open blocking: {', '.join(r.blocking_open) or 'none'}; advisory: {', '.join(r.advisory) or 'none'}")
    if state.review.frozen_at:
        echo(f"Frozen at {state.review.frozen_at} (sha256 {state.review.frozen_sha256[:12]})")


# ------------------------------------------------------------------ env

@env_app.command("init")
def env_init(lock: Path = typer.Argument(..., help="Lock file to record (uv.lock, requirements.txt, environment.yml)."),
             inv_id: Optional[str] = INV_OPT) -> None:
    """Record the locked environment before execution starts (replaces the empty v1 lock)."""
    prog, inv, state = _ctx(inv_id)
    if state.phase >= Phase.EXECUTING:
        raise CraftError("execution has started; changes go through `craft env propose`")
    envlock.init_lock(inv, state, lock)
    state.save(inv.root)
    echo(f"env.lock v{state.env.version} recorded (sha256 {state.env.lock_sha256[:12]}).")


@env_app.command("propose")
def env_propose(package: str, reason: str = typer.Option(..., "--reason"), inv_id: Optional[str] = INV_OPT) -> None:
    """Propose an addition to the locked environment; execution halts until the researcher approves."""
    prog, inv, state = _ctx(inv_id)
    envlock.propose(inv, state, package, reason)
    state.save(inv.root)
    echo(f"Proposed adding '{package}' (env v{state.env.version} -> v{state.env.version + 1}). "
         "Execution is halted: no verdicts can be filed until the researcher runs `craft env approve` (or `craft env reject`).")


@env_app.command("approve")
def env_approve(lock: Optional[Path] = typer.Option(None, "--lock", help="New lock file; default appends the package line."),
                inv_id: Optional[str] = INV_OPT) -> None:
    """RESEARCHER ONLY. Accept the pending environment proposal; bumps the env version."""
    require_human("env approve")
    prog, inv, state = _ctx(inv_id)
    prop = envlock.pending(state)
    if not prop:
        raise CraftError("no pending proposal")
    echo(f"Proposal: add '{prop['package']}' — {prop['reason']}")
    if not confirm("Approve this environment change?"):
        raise typer.Exit(code=1)
    v = envlock.approve(inv, state, lock)
    state.attend("approve-env", prop["package"], prop["reason"])
    state.save(inv.root)
    echo(f"Environment is now v{v} (sha256 {state.env.lock_sha256[:12]}). Subsequent verdicts record v{v}.")


@env_app.command("reject")
def env_reject(note: str = typer.Option(..., "--note"), inv_id: Optional[str] = INV_OPT) -> None:
    """RESEARCHER ONLY. Reject the pending environment proposal."""
    require_human("env reject")
    prog, inv, state = _ctx(inv_id)
    envlock.reject(inv, state, note)
    state.attend("reject-env", "env", note)
    state.save(inv.root)
    echo("Proposal rejected; execution may continue with the current environment.")


# ------------------------------------------------------------------ verdict / finish

@app.command()
def verdict(experiment: str, criterion: str = typer.Option(..., "--criterion"),
            evidence: Path = typer.Option(..., "--evidence", help="Evidence file under experiments/<exp>/evidence/"),
            metric: Optional[str] = typer.Option(None, "--metric", help="Metric key in the evidence file (default: the criterion's metric)."),
            exploratory: list[Path] = typer.Option([], "--exploratory", help="Exploratory dirs/files to link for transparency (never evidence)."),
            seed: list[str] = typer.Option([], "--seed"), data_id: list[str] = typer.Option([], "--data-id"),
            inv_id: Optional[str] = INV_OPT) -> None:
    """Compute a verdict for one criterion from an evidence file, against the frozen threshold."""
    prog, inv, state = _ctx(inv_id)
    state.require_untainted("file a verdict")
    state.require_phase(Phase.EXECUTING, action="file a verdict")
    if state.env.pending_proposal:
        raise CraftError(f"execution is halted: environment proposal '{state.env.pending_proposal['package']}' awaits `craft env approve`.")
    fm, _ = read_doc(inv.hypothesis)
    crits = criteria_table(fm)
    if criterion not in crits:
        raise CraftError(f"'{criterion}' is not a criterion in the frozen hypothesis ({', '.join(crits) or 'none'})")
    crit = crits[criterion]
    ev = evidence.resolve()
    exp_dir = inv.experiment(experiment).resolve()
    try:
        rel_ev = ev.relative_to(inv.evidence_dir(experiment).resolve())
    except ValueError:
        where = "exploratory" if "exploratory" in ev.parts else "outside"
        raise CraftError(
            f"evidence must live under experiments/{experiment}/evidence/. {ev} is {where} that area"
            + (": exploratory numbers are never evidence for a criterion, however good they look." if where == "exploratory" else ".")
        )
    if not ev.exists():
        raise CraftError(f"{ev} does not exist")
    links = []
    for x in exploratory:
        xr = x.resolve()
        try:
            xr.relative_to(inv.exploratory_dir(experiment).resolve())
        except ValueError:
            raise CraftError(f"--exploratory {x} must be under experiments/{experiment}/exploratory/")
        links.append(str(xr.relative_to(inv.root.resolve())))
    data = load_evidence(ev)
    m = extract(data, metric or crit["metric"])
    op, thr = crit["op"], float(crit["threshold"])
    label, rationale = label_for(m, op, thr)
    seeds = seed or (m.seeds if m.seeds else [])
    data_ids = data_id or ([m.data_id] if m.data_id else [])
    if not seeds:
        raise CraftError("no seeds recorded: put `seeds` in the evidence file or pass --seed (reproducibility record)")
    if not data_ids:
        raise CraftError("no data identifier: put `data_id` in the evidence file or pass --data-id")

    # kill criteria check (problem.md, frozen)
    pfm, _ = read_doc(inv.problem)
    killed = None
    for k in kill_criteria(pfm):
        if k["metric"] in _metric_names(data):
            km = extract(data, k["metric"])
            if compare(k["op"], km.point, float(k["value"])):
                killed = (k, km)
                break

    vfm = {
        "experiment": experiment, "criterion": criterion, "label": label, "rationale": rationale,
        "metric": m.metric, "op": op, "threshold": thr,
        "observed": m.point, "ci95": [m.ci_low, m.ci_high], "n": m.n, "unit": m.unit,
        "uncertainty_source": m.source,
        "evidence": [{"path": str(ev.relative_to(inv.root.resolve())), "sha256": sha256_file(ev)}],
        "exploratory_links": links,
        "exploratory_note": "linked for transparency; none of these numbers are evidence for any criterion" if links else None,
        "seeds": seeds, "data_ids": data_ids,
        "env_version": state.env.version, "env_lock_sha256": state.env.lock_sha256,
        "hypothesis_sha256": state.review.frozen_sha256, "problem_sha256": state.problem_sha256,
        "created": now_iso(),
        "kill_triggered": {"criterion": killed[0]["id"], "condition": killed[0]["condition"], "observed": killed[1].point} if killed else None,
    }
    body = [f"# Verdict — {experiment} / {criterion}: **{label.upper()}**", "",
            f"Criterion {criterion}: {m.metric} {op} {thr} under: {crit.get('conditions')}",
            f"Observed: {m.point:.6g} (95% CI [{m.ci_low:.6g}, {m.ci_high:.6g}], n={m.n}) — {rationale}", "",
            "Evidence: " + ", ".join(f"`{e['path']}` (sha256 {e['sha256'][:12]})" for e in vfm["evidence"]),
            f"Reproducibility: seeds {seeds}; data {data_ids}; env v{state.env.version} ({(state.env.lock_sha256 or '')[:12]}); "
            f"hypothesis {(state.review.frozen_sha256 or '')[:12]}"]
    if links:
        body += ["", "Exploratory (not evidence): " + ", ".join(f"`{l}`" for l in links)]
    if killed:
        body += ["", f"KILL CRITERION {killed[0]['id']} MET: {killed[0]['condition']} (observed {killed[1].point:.6g}). Execution halted."]
    vpath = inv.verdict(experiment, criterion)
    if vpath.exists():
        vpath.chmod(0o644)
    vpath.write_text(render_verdict(vfm, body), encoding="utf-8")
    vpath.chmod(0o444)
    rel_v = str(vpath.relative_to(inv.root))
    state.verdicts = [v for v in state.verdicts if not (v.experiment == experiment and v.criterion == criterion)]
    state.verdicts.append(VerdictRef(experiment=experiment, criterion=criterion, label=label, file=rel_v, when=now_iso()))
    echo(f"Verdict for {criterion} ({experiment}): {label.upper()} — {rationale}. Written to {rel_v}.")
    if killed:
        state.kill.triggered = True
        state.kill.criterion = killed[0]["id"]
        state.kill.when = now_iso()
        state.kill.evidence = str(ev.relative_to(inv.root.resolve()))
        state.kill.observed = killed[1].point
        state.phase = Phase.CLOSING
        state.save(inv.root)
        echo(f"KILL CRITERION {killed[0]['id']} MET ({killed[0]['condition']}; observed {killed[1].point:.6g}). "
             "Remaining experiments are halted; the investigation is routed to closure. Write closure.md, then the "
             "researcher runs `craft close`.")
        return
    state.save(inv.root)
    done = {v.criterion for v in state.verdicts}
    missing = [c for c in crits if c not in done]
    if missing:
        echo(f"Criteria still without a verdict: {', '.join(missing)}.")
    else:
        echo("Every criterion has a verdict. Run `craft finish` to route to closure.")


def _metric_names(data: dict) -> set[str]:
    names = set()
    if isinstance(data.get("metrics"), dict):
        names |= set(data["metrics"].keys())
    if data.get("metric"):
        names.add(data["metric"])
    return names


@app.command()
def finish(inv_id: Optional[str] = INV_OPT) -> None:
    """Move an executing investigation to closing once every criterion has a verdict."""
    prog, inv, state = _ctx(inv_id)
    state.require_phase(Phase.EXECUTING, action="finish")
    fm, _ = read_doc(inv.hypothesis)
    missing = [c for c in criteria_table(fm) if c not in {v.criterion for v in state.verdicts}]
    if missing:
        raise CraftError(f"criteria without a verdict: {', '.join(missing)}. File them, or the researcher closes with --incomplete.")
    state.phase = Phase.CLOSING
    state.save(inv.root)
    if not inv.closure.exists():
        inv.closure.write_text(_template("closure.md").replace("{id}", state.id), encoding="utf-8")
    echo("Phase: closing. Write closure.md (anomalies go to open questions), then the researcher runs `craft close`.")


# ------------------------------------------------------------------ close (human)

@app.command()
def close(inv_id: Optional[str] = INV_OPT, note: str = typer.Option("", "--note"),
          incomplete: bool = typer.Option(False, "--incomplete", help="Close an executing investigation without all verdicts.")) -> None:
    """RESEARCHER ONLY. Close the investigation: route outcomes to memory, archive it intact."""
    require_human("close")
    prog, inv, state = _ctx(inv_id)
    problems = verify_investigation(prog, state.id)
    if problems:
        raise CraftError("integrity problems block closure:\n  " + "\n  ".join(problems))
    state = InvestigationState.load(inv.root)
    state.require_untainted("close")
    if state.phase == Phase.EXECUTING and incomplete:
        state.phase = Phase.CLOSING
        state.attend("close-incomplete", state.id, note or "closed before all criteria had verdicts")
    state.require_phase(Phase.CLOSING, action="close")
    echo(f"Closing {state.id}: {len(state.verdicts)} verdict(s)" + (f", kill {state.kill.criterion}" if state.kill.triggered else ""))
    for v in state.verdicts:
        echo(f"  {v.criterion} ({v.experiment}): {v.label}")
    if inv.closure.exists():
        cfm, _ = read_doc(inv.closure)
        echo(f"  anomalies: {len(cfm.get('anomalies') or [])}")
    if not confirm("Close and archive? Memory will be updated."):
        raise typer.Exit(code=1)
    routed = close_investigation(prog, inv, state, note)
    echo(f"Closed. findings +{len(routed['finding'])}, refuted +{len(routed['refuted'])}, open questions +{len(routed['open'])}. "
         f"Archived to archive/{state.id}/ (read-only).")


# ------------------------------------------------------------------ reopen / untaint (human)

@reopen_app.command("problem")
def reopen_problem(inv_id: Optional[str] = INV_OPT, note: str = typer.Option(..., "--note")) -> None:
    """RESEARCHER ONLY. Reopen an approved problem statement for editing (before the design is frozen)."""
    require_human("reopen problem")
    prog, inv, state = _ctx(inv_id)
    state.require_phase(Phase.DESIGNING, Phase.RESPONDING, action="reopen problem")
    if not confirm("Reopen problem.md? Approval is withdrawn."):
        raise typer.Exit(code=1)
    thaw_file(inv.problem)
    state.problem_sha256 = None
    state.phase = Phase.FRAMING
    state.attend("reopen", "problem.md", note)
    state.save(inv.root)
    echo("problem.md reopened; phase: framing.")


@reopen_app.command("review")
def reopen_review(inv_id: Optional[str] = INV_OPT, note: str = typer.Option(..., "--note")) -> None:
    """RESEARCHER ONLY. After an exhausted review, start a fresh cycle once the design was genuinely changed."""
    require_human("reopen review")
    prog, inv, state = _ctx(inv_id)
    state.require_phase(Phase.RESPONDING, action="reopen review")
    last = state.review.rounds[-1]
    if sha256_file(inv.hypothesis) == last.hypothesis_sha256:
        raise CraftError("hypothesis.md has not changed since the last round; reopening requires a genuine design change first.")
    if not confirm(f"Archive {len(state.review.rounds)} round(s) and start a fresh review cycle?"):
        raise typer.Exit(code=1)
    k = len(state.review.history) + 1
    hist = inv.review_dir / f"history-{k}"
    hist.mkdir()
    for p in list(inv.review_dir.iterdir()):
        if p.is_file():
            p.chmod(0o644)
            shutil.move(str(p), str(hist / p.name))
    state.review.history.append([r.model_dump() for r in state.review.rounds])
    state.review.rounds = []
    state.review.exhausted = False
    state.phase = Phase.DESIGNING
    state.attend("reopen", "review", note)
    state.save(inv.root)
    echo(f"Review reopened (previous rounds in review/history-{k}/). Phase: designing.")


@app.command()
def untaint(inv_id: Optional[str] = INV_OPT, note: str = typer.Option(..., "--note"),
            accept_current: bool = typer.Option(False, "--accept-current", help="Re-record hashes of the current frozen files (logged).")) -> None:
    """RESEARCHER ONLY. Clear an integrity failure after reviewing it."""
    require_human("untaint")
    prog, inv, state = _ctx(inv_id)
    if not state.tainted:
        echo("not tainted")
        return
    echo("Taint reasons:\n  " + "\n  ".join(state.taint_reasons))
    if accept_current:
        if not confirm("Re-record the CURRENT contents of frozen files as authoritative? This is logged."):
            raise typer.Exit(code=1)
        if state.problem_sha256 and inv.problem.exists():
            state.problem_sha256 = freeze_file(inv.problem)
        if state.review.frozen_sha256 and inv.hypothesis.exists():
            state.review.frozen_sha256 = freeze_file(inv.hypothesis)
        if state.env.lock_sha256 and inv.env_lock.exists():
            inv.env_lock.chmod(0o444)
            state.env.lock_sha256 = sha256_file(inv.env_lock)
    state.tainted = False
    reasons = list(state.taint_reasons)
    state.taint_reasons = []
    state.attend("untaint", state.id, note + (" [accepted current contents]" if accept_current else "") + " | " + "; ".join(reasons))
    state.save(inv.root)
    remaining = verify_investigation(prog, state.id)
    if remaining:
        raise CraftError("still failing integrity (restore the files or use --accept-current):\n  " + "\n  ".join(remaining))
    echo("Untainted.")


# ------------------------------------------------------------------ status / explain / attention / verify

@app.command()
def status(inv_id: Optional[str] = INV_OPT, as_json: bool = typer.Option(False, "--json")) -> None:
    """Phase, open objections, what is blocked and why."""
    prog = _prog()
    if as_json:
        out = {}
        for i in prog.list_investigations():
            st = InvestigationState.load(prog.investigation_dir(i))
            _refresh(InvestigationPaths(prog.investigation_dir(i)), st)
            out[i] = dump_public(st)
        echo(json.dumps(out, indent=2))
        return
    for i in prog.list_investigations():
        st = InvestigationState.load(prog.investigation_dir(i))
        _refresh(InvestigationPaths(prog.investigation_dir(i)), st)
    echo(status_text(prog))


@app.command()
def explain(entry_id: str = typer.Argument(..., help="Memory entry id, e.g. F-0001 or R-0002")) -> None:
    """Walk the chain claim -> criterion -> observed -> files, verifying every link resolves."""
    prog = _prog()
    rec = mem.find_entry(prog, entry_id)
    if rec is None:
        raise CraftError(f"no memory entry {entry_id}")
    echo(f"[{rec['kind']}] {entry_id}: {rec.get('claim') or rec.get('question')}")
    echo(f"  investigation: {rec.get('investigation')}  closed: {rec.get('closed', '')[:10]}")
    lin = rec.get("lineage")
    broken = 0
    if not lin:
        echo("  (no evidence lineage: this entry is an open question or anomaly)")
        return
    echo(f"  criterion {lin['criterion']} in experiment {lin['experiment']}: observed {lin.get('observed')} vs threshold {lin.get('threshold')}")
    vf = prog.root / lin["verdict_file"]
    ok = vf.exists() and (lin.get("verdict_sha256") is None or sha256_file(vf) == lin["verdict_sha256"])
    broken += 0 if ok else 1
    echo(f"  verdict file {lin['verdict_file']}: {'resolves' if ok else 'BROKEN'}")
    for e in lin.get("evidence", []):
        p = prog.root / e["path"]
        ok = p.exists() and sha256_file(p) == e["sha256"]
        broken += 0 if ok else 1
        echo(f"  evidence {e['path']} (sha256 {e['sha256'][:12]}): {'resolves' if ok else 'BROKEN'}")
    hyp = prog.archive_dir / rec["investigation"] / "hypothesis.md"
    ok = hyp.exists() and (lin.get("hypothesis_sha256") is None or sha256_file(hyp) == lin["hypothesis_sha256"])
    broken += 0 if ok else 1
    echo(f"  frozen hypothesis archive/{rec['investigation']}/hypothesis.md: {'resolves' if ok else 'BROKEN'}")
    echo(f"  env v{lin.get('env_version')}; seeds {lin.get('seeds')}; data {lin.get('data_ids')}")
    if broken:
        raise CraftError(f"{broken} link(s) do not resolve")
    echo("Every link resolves.")


@app.command()
def attention(inv_id: Optional[str] = INV_OPT) -> None:
    """The researcher's recorded decisions (what they had to read and approve)."""
    prog = _prog()
    ids = [inv_id] if inv_id else prog.list_investigations() + prog.list_archived()
    for i in ids:
        root = prog.investigation_dir(i) if prog.investigation_dir(i).exists() else prog.archive_dir / i
        st = InvestigationState.load(root)
        for a in st.attention:
            echo(f"{a.when}  {i:<12} {a.kind:<18} {a.subject}  {a.note}")
        for ack in st.acknowledgements:
            echo(f"{ack.when}  {i:<12} {'acknowledge':<18} {ack.ref}  {ack.justification}")


@app.command()
def verify() -> None:
    """Integrity of frozen documents, locks, review files, verdicts and memory."""
    prog = _prog()
    problems = verify_all(prog)
    if problems:
        for p in problems:
            echo(f"- {p}")
        raise typer.Exit(code=1)
    echo("All frozen artifacts intact.")


@app.command()
def hook(event: str = typer.Argument(..., help="pre-tool-use | user-prompt-submit | session-start | stop")) -> None:
    """Claude Code hook entry point (reads the hook JSON on stdin)."""
    fn = hooks.EVENTS.get(event)
    if fn is None:
        raise CraftError(f"unknown hook event '{event}'")
    raise typer.Exit(code=fn())


def main() -> None:
    try:
        app(standalone_mode=False)
    except CraftError as e:
        typer.echo(f"craft: {e}", err=True)
        sys.exit(e.exit_code)
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except typer.Abort:
        sys.exit(1)


if __name__ == "__main__":
    main()
