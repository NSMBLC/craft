"""`craft` — the one rule engine. Every gate, transition and computation lives here."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from . import decisions, envlock, hooks, registry
from . import memory as mem
from .artifacts import review as rv
from .artifacts.hypothesis import criteria_table, validate_hypothesis
from .artifacts.literature import add_source, lint_priority_claims, load_sources, validate_literature
from .artifacts.plan import validate_plan
from .artifacts.problem import kill_criteria, validate_problem
from .artifacts.verdict import compare, extract, label_for, load_evidence, render_verdict
from .cli_support import decisions_text, explain_text, load_context, status_text, verify_all
from .human import confirm, require_human
from .integrity import make_writable
from .paths import DEFAULT_CONFIG, PROGRAMME_MARKER, InvestigationPaths, Programme, find_programme_root
from .referee import build_round1_prompt, build_round2_prompt, run_referee
from .state import Acknowledgement, InvestigationState, Phase, ReviewRound, VerdictRef, new_state
from .util import CraftError, now_iso, read_doc, sha256_file, write_yaml

app = typer.Typer(help="CRAFT: disciplined computational research inside a GenAI session.", no_args_is_help=True,
                  add_completion=False)
lit_app = typer.Typer(help="Literature map: sources read in full vs consulted-and-rejected (Journey 2). Open at any time.", no_args_is_help=True)
review_app = typer.Typer(help="Independent review (Journey 4). `craft review` reviews every hypothesis that is ready.", invoke_without_command=True)
reopen_app = typer.Typer(help="Retired: nothing is frozen in CRAFT v2, so there is nothing to reopen.", no_args_is_help=True)
app.add_typer(lit_app, name="literature")
app.add_typer(lit_app, name="lit", hidden=True)
app.add_typer(review_app, name="review")
app.add_typer(reopen_app, name="reopen")

INV_OPT = typer.Option(None, "--inv", help="Investigation id (defaults to the only open one).")


def echo(msg: str = "") -> None:
    typer.echo(msg)


def _prog() -> Programme:
    return Programme(find_programme_root())


def _ctx(inv_id: Optional[str]) -> tuple[Programme, InvestigationPaths, InvestigationState]:
    prog = _prog()
    inv, state = load_context(prog, inv_id)
    return prog, inv, state


def _template(name: str) -> str:
    return resources.files("craft.templates").joinpath(name).read_text(encoding="utf-8")


def _write_record(inv: InvestigationPaths, state: InvestigationState, path: Path, text: str) -> str:
    """Write a file only `craft` writes, and record its hash so any later change is detected."""
    path.parent.mkdir(parents=True, exist_ok=True)
    make_writable(path)
    path.write_text(text, encoding="utf-8")
    digest = sha256_file(path)
    state.record(inv.rel(path), digest)
    return digest


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
    echo("Next: open your GenAI session here and type /craft-help to see your commands "
         "(/craft-approve, /craft-reject, /craft-close, /craft-resolve, /craft-status).")


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
            import re as _re
            pattern = _re.compile(r"<!-- craft:begin -->.*?<!-- craft:end -->\n?", _re.S)
            if pattern.search(text) and pattern.search(text).group(0) != block:
                cm.write_text(pattern.sub(lambda m: block, text, count=1), encoding="utf-8")
                created.append("CLAUDE.md (refreshed CRAFT block; your own text untouched)")
    else:
        cm.write_text(block, encoding="utf-8")
        created.append("CLAUDE.md")
    for name in ("craft-env", "craft-untaint"):
        retired = claude_dir / "skills" / name / "SKILL.md"
        if retired.exists() and "Researcher decision" in retired.read_text(encoding="utf-8"):
            shutil.rmtree(retired.parent)
            created.append(f"removed retired .claude/skills/{name}")
    for skill in adapter.joinpath("skills").iterdir():
        src = skill.joinpath("SKILL.md")
        if not src.is_file():
            continue
        skill_dir = claude_dir / "skills" / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        sk = skill_dir / "SKILL.md"
        content = src.read_text(encoding="utf-8")
        if not sk.exists() or (skill.name != "craft" and sk.read_text(encoding="utf-8") != content):
            sk.write_text(content, encoding="utf-8")
            created.append(f".claude/skills/{skill.name}/SKILL.md")
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
    inv.hypotheses_dir.mkdir()
    inv.review_dir.mkdir()
    inv.experiments_dir.mkdir()
    envlock.init_lock(inv, state, lock)
    state.save(root)
    echo(f"Created investigations/{inv_id}/ (phase: framing).")
    if acks:
        echo(f"Recorded {len(acks)} memory acknowledgement(s) in problem.md.")
    echo("Next: interview the researcher about readers and fill problem.md; `craft validate problem`; "
         "then the researcher types `/craft-approve`.")


# ------------------------------------------------------------------ validate / lint

@app.command()
def validate(artifact: str = typer.Argument("all", help="problem | literature | hypotheses | <hypothesis id, e.g. H2> | plans | all"),
             inv_id: Optional[str] = INV_OPT) -> None:
    """Check artifacts against their required shape. Reports; never rewrites.

    `all` lists incomplete hypothesis drafts as ideas without failing; `hypotheses` or an id fails on them.
    """
    prog, inv, state = _ctx(inv_id)
    results, notes = [], []
    hyp_ids = inv.hypothesis_ids()
    if artifact in ("problem", "all"):
        results.append(validate_problem(inv.problem, int(prog.config["limits"]["problem_max_words"])))
    if artifact in ("literature", "all"):
        if inv.sources.exists() or artifact == "literature":
            results.append(validate_literature(inv.sources))
    if artifact in ("hypotheses", "hypothesis"):
        if not hyp_ids:
            raise CraftError("no hypotheses yet: write hypotheses/H1.md")
        results += [validate_hypothesis(inv.hypothesis(h)) for h in hyp_ids]
    elif artifact in hyp_ids:
        results.append(validate_hypothesis(inv.hypothesis(artifact)))
    elif artifact == "all":
        for h in hyp_ids:
            hv = validate_hypothesis(inv.hypothesis(h))
            (results if hv.ok else notes).append(hv)
    if artifact in ("plans", "all"):
        results += [validate_plan(inv, state, e) for e in inv.experiment_names() if inv.experiment_plan(e).exists()]
    if not results and not notes:
        if artifact in ("problem", "literature", "hypotheses", "hypothesis", "plans", "all"):
            echo("Nothing to validate yet.")
            return
        raise CraftError(f"'{artifact}' is not problem, literature, hypotheses, plans, all, or a hypothesis id ({', '.join(hyp_ids) or 'none yet'})")
    ok = True
    for r in results:
        echo(r.render())
        ok = ok and r.ok
    for r in notes:
        echo(f"{r.artifact}: incomplete draft (an idea until it is filled in; `craft validate {Path(r.artifact).stem}` for details)")
    if artifact == "all":
        docs = [inv.problem, inv.lit_map] + [inv.hypothesis(h) for h in hyp_ids]
        for doc in docs:
            if doc.exists():
                for prob in lint_priority_claims(doc, inv.sources):
                    echo(f"  [error] {inv.rel(doc)}: {prob}")
                    ok = False
    if not ok:
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
    """Record a source: used (full text on disk) or consulted-and-rejected (one-line reason). Any time before closure."""
    prog, inv, state = _ctx(inv_id)
    state.require_phase(Phase.FRAMING, Phase.OPEN, Phase.CLOSING, action="add a source")
    if fulltext is None and not abstract_only:
        raise CraftError("give --fulltext <path> for a source you read, or --abstract-only --reason for one you did not")
    entry = add_source(inv.sources, key, title, None if abstract_only else fulltext, reason, claims, method, relation, does_not_cover)
    echo(f"Added {key} as {entry['status']}.")


@lit_app.command("closest")
def lit_closest(key: str, delta: str = typer.Option(..., "--delta", help="One paragraph: what this adds beyond it."),
                inv_id: Optional[str] = INV_OPT) -> None:
    """Name the single closest prior work and the delta against it (update it as the field moves)."""
    prog, inv, state = _ctx(inv_id)
    data = load_sources(inv.sources)
    if key not in {s.get("key") for s in data["sources"] if s.get("status") == "used"}:
        raise CraftError(f"'{key}' is not a used source (full text read)")
    data["closest_prior_work"] = key
    data["delta"] = delta
    write_yaml(inv.sources, data)
    echo(f"closest_prior_work = {key}")


# ------------------------------------------------------------------ approve (human)

@app.command()
def approve(what: Optional[str] = typer.Argument(None, help="problem | package (default: whatever is pending)"),
            inv_id: Optional[str] = INV_OPT, note: str = typer.Option("", "--note"),
            lock: Optional[Path] = typer.Option(None, "--lock", help="(package) new lock file; default appends the package line.")) -> None:
    """RESEARCHER ONLY. Approve what the agent is waiting on: the problem statement or a package proposal."""
    require_human("approve")
    if what not in (None, "problem", "package"):
        raise CraftError("`craft approve [problem|package]`; hypotheses are registered by review, not approval")

    def run(prog):
        subject = what or decisions.pending_subject(prog, inv_id, "approve")
        if subject == "problem":
            return decisions.approve_problem(prog, inv_id, note, _tty_confirm, "terminal")
        return decisions.env_approve(prog, inv_id, lock, _tty_confirm, "terminal")

    echo(_decide(run))


@app.command()
def reject(what: Optional[str] = typer.Argument(None, help="package"), note: str = typer.Option(..., "--note"),
           inv_id: Optional[str] = INV_OPT) -> None:
    """RESEARCHER ONLY. Refuse the pending package proposal; execution continues with the current environment."""
    if what not in (None, "package"):
        raise CraftError("only a package proposal can be rejected")
    require_human("reject")

    def run(prog):
        decisions.pending_subject(prog, inv_id, "reject")
        return decisions.env_reject(prog, inv_id, note, "terminal")

    echo(_decide(run))


def _tty_confirm(preview: str) -> bool:
    lines = preview.rsplit("\n", 1)
    if len(lines) == 2:
        echo(lines[0])
        return confirm(lines[1])
    return confirm(preview)


def _decide(fn) -> str:
    try:
        return fn(_prog())
    except decisions.Declined as e:
        echo(str(e))
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ review

class _NotDue(CraftError):
    """A hypothesis with nothing to review (registered and unchanged, dropped); quiet unless named."""


@review_app.callback()
def review_root(ctx: typer.Context,
                hyp: list[str] = typer.Option([], "--hyp", help="Review only this hypothesis (repeatable). Default: every one that is ready."),
                inv_id: Optional[str] = INV_OPT) -> None:
    """Run the independent referee on every hypothesis that is ready. A clean pass registers it."""
    if ctx.invoked_subcommand is None:
        review_request(hyp, inv_id)


@review_app.command("request", hidden=True)
def review_request(hyp: list[str] = typer.Option([], "--hyp"), inv_id: Optional[str] = INV_OPT) -> None:
    """Alias of `craft review`."""
    prog, inv, state = _ctx(inv_id)
    state.require_untainted("request review")
    if state.phase == Phase.FRAMING:
        raise CraftError("the problem statement has not been approved yet; hypotheses are reviewed after the "
                         "researcher types `/craft-approve`.")
    state.require_phase(Phase.OPEN, action="request review")
    if inv.sources.exists():
        lv = validate_literature(inv.sources)
        if not lv.ok:
            raise CraftError("the literature map is not complete:\n" + lv.render())
    targets = list(hyp) or inv.hypothesis_ids()
    if not targets:
        raise CraftError("no hypotheses to review: write hypotheses/H1.md first")
    due, skipped = [], []
    for hid in targets:
        try:
            due.append((hid, _review_step(prog, inv, state, hid)))
        except _NotDue as e:
            if hyp:
                raise CraftError(str(e)) from None
        except CraftError as e:
            if hyp:
                raise
            first = str(e).splitlines()[0]
            skipped.append(f"{hid}: {first}" + (f" (`craft validate {hid}` for details)" if "not complete" in first else ""))
    if not due:
        raise CraftError("nothing is ready for review:\n  " + ("\n  ".join(skipped) or "every hypothesis is registered and unchanged"))
    for hid, step in due:
        _run_review(prog, inv, state, hid, step)
    for line in skipped:
        echo(f"Not reviewed — {line}")


def _review_step(prog: Programme, inv: InvestigationPaths, state: InvestigationState, hid: str) -> str:
    """What reviewing `hid` means right now: 'round1', 'round2' or 'new-cycle'. Raises with the reason otherwise."""
    path = inv.hypothesis(hid)
    if not path.exists():
        raise _NotDue(f"hypotheses/{hid}.md does not exist")
    fm, _ = read_doc(path)
    if fm.get("dropped"):
        raise _NotDue(f"{hid} is dropped ({fm['dropped']})")
    rec = state.hyp(hid)
    sha = sha256_file(path)
    limit = int(prog.config["limits"]["review_rounds"])

    def complete() -> None:
        v = validate_hypothesis(path)
        if not v.ok:
            raise CraftError(f"{hid} is not complete enough to review:\n" + v.render())

    if rec.registered_sha256:
        if sha == rec.registered_sha256:
            raise _NotDue(f"{hid} is registered and unchanged")
        if registry.evidence_exists_for(inv, state, hid):
            raise CraftError(
                f"{hid} changed after evidence for it was produced, so it cannot be registered again: criteria fixed "
                "after the data are not a pre-registration. Its verdicts stay computed against the registered version, "
                "and any criteria change is shown as post-hoc. To test the new version confirmatorily, write it as a "
                f"new hypothesis (derived_from: {hid}) and review that."
            )
        complete()
        return "new-cycle"
    if rec.rounds and rec.open_blocking:
        last = rec.rounds[-1]
        if rec.exhausted or len(rec.rounds) >= limit:
            if sha == last.hypothesis_sha256:
                raise CraftError(
                    f"review of {hid} is capped at {limit} rounds and round {last.n} left blocking objections unresolved "
                    f"({', '.join(last.blocking_open)}). The remaining items must be genuinely fixed in hypotheses/{hid}.md; "
                    f"then `craft review --hyp {hid}` starts a new review cycle. Arguing them down is not a path."
                )
            complete()
            return "new-cycle"
        missing = [i for i in last.blocking_open if i not in last.responses]
        if missing:
            raise CraftError(
                f"every blocking objection on {hid} must be answered before the next round: missing responses for "
                + ", ".join(f"{hid}:{m}" for m in missing)
                + ". Use `craft review respond <H:O> --pointer <doc#section> --note ...`."
            )
        return "round2"
    complete()
    return "round1"


def _new_cycle(inv: InvestigationPaths, state: InvestigationState, hid: str) -> None:
    """Archive the current review cycle (and any registration) under review/<id>/cycle-<k>/."""
    rec = state.hyp(hid)
    k = len(rec.cycles) + 1
    rdir = inv.hyp_review_dir(hid)
    dest = rdir / f"cycle-{k}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(rdir.iterdir()):
        if f.is_file():
            old = inv.rel(f)
            shutil.move(str(f), str(dest / f.name))
            if old in state.records:
                state.records[inv.rel(dest / f.name)] = state.records.pop(old)
    rec.cycles.append([r.model_dump() for r in rec.rounds])
    rec.rounds = []
    rec.exhausted = False
    rec.registered_sha256 = None
    rec.registered_at = None


def _run_review(prog: Programme, inv: InvestigationPaths, state: InvestigationState, hid: str, step: str) -> None:
    if step == "new-cycle":
        _new_cycle(inv, state, hid)
        k = len(state.hyp(hid).cycles)
        echo(f"{hid}: starting review cycle {k + 1} (earlier rounds kept in review/{hid}/cycle-{k}/).")
    rec = state.hyp(hid)
    path = inv.hypothesis(hid)
    limit = int(prog.config["limits"]["review_rounds"])
    n = len(rec.rounds) + 1
    cfg = prog.config["referee"]
    backend = os.environ.get("CRAFT_REFEREE_BACKEND") or cfg.get("backend", "claude")
    if n == 1:
        sys_p, user_p = build_round1_prompt(inv, hid)
        data = _run_checked(cfg, sys_p, user_p, rv.ROUND1_SCHEMA, n, hid, lambda d: rv.check_round1(d))
        objections = data.get("objections", [])
        rnd = ReviewRound(n=n, when=now_iso(), backend=backend, hypothesis_sha256=sha256_file(path), objections=objections,
                          blocking_open=[o["id"] for o in objections if o["severity"] == "blocking"],
                          advisory=[o["id"] for o in objections if o["severity"] == "advisory"])
    else:
        prev = rec.rounds[-1]
        round1 = json.loads(inv.review_round(hid, 1).read_text(encoding="utf-8"))
        snap = inv.review_snapshot(hid, prev.n)
        old = snap.read_text(encoding="utf-8") if snap.exists() else ""
        diff = "".join(difflib.unified_diff(old.splitlines(True), path.read_text(encoding="utf-8").splitlines(True),
                                            f"hypotheses/{hid}.md (round {prev.n})", f"hypotheses/{hid}.md (now)"))
        sys_p, user_p = build_round2_prompt(inv, hid, round1, prev.responses, diff)
        data = _run_checked(cfg, sys_p, user_p, rv.ROUND2_SCHEMA, n, hid, lambda d: rv.check_round2(d, prev.blocking_open))
        judgements = data.get("judgements", [])
        unresolved = [j["id"] for j in judgements if j["decision"] == "unresolved" and j["id"] in prev.blocking_open]
        rnd = ReviewRound(n=n, when=now_iso(), backend=backend, hypothesis_sha256=sha256_file(path), judgements=judgements,
                          blocking_open=unresolved, advisory=prev.advisory)
    rp = inv.review_round(hid, n)
    _write_record(inv, state, rp, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    _write_record(inv, state, inv.review_prompt(hid, n), f"# System\n\n{sys_p}\n\n# Documents and instructions\n\n{user_p}\n")
    _write_record(inv, state, inv.review_snapshot(hid, n), path.read_text(encoding="utf-8"))
    rec.rounds.append(rnd)

    echo(f"{hid}: review round {n} ({rnd.backend}) written to {rp.relative_to(prog.root)}")
    if n == 1:
        for o in rnd.objections:
            echo(f"  [{o['severity']}] {hid}:{o['id']} ({o['category']}) -> {o['target']['document']} § {o['target']['section']}")
            echo(f"      {o['statement']}")
            echo(f"      adequate answer: {o['adequate_answer']}")
    else:
        for j in rnd.judgements:
            echo(f"  {hid}:{j['id']}: {j['decision']} — {j['reason']}")
    if not rnd.blocking_open:
        digest = _write_record(inv, state, inv.registered(hid), path.read_text(encoding="utf-8"))
        rec.registered_sha256 = digest
        rec.registered_at = now_iso()
        rec.exhausted = False
        rec.registrations.append({"when": rec.registered_at, "sha256": digest, "cycle": len(rec.cycles) + 1, "round": n})
        state.save(inv.root)
        adv = f" {len(rnd.advisory)} advisory note(s) recorded." if rnd.advisory else ""
        echo(f"{hid}: no blocking objections.{adv} {hid} is now REGISTERED (sha256 {digest[:12]}): its criteria are binding, "
             "evidence may be produced for it, and verdicts are computed against this version. The file stays editable; "
             "a later change to its criteria is shown as post-hoc in every verdict.")
        return
    if n >= limit:
        rec.exhausted = True
    state.save(inv.root)
    echo(f"{hid}: {len(rnd.blocking_open)} blocking objection(s) open: {', '.join(rnd.blocking_open)}.")
    if rec.exhausted:
        echo(f"Round cap reached for {hid}: these must be genuinely fixed in hypotheses/{hid}.md; then "
             f"`craft review --hyp {hid}` starts a new cycle.")
    else:
        echo(f"Change the design, then `craft review respond {hid}:<id> --pointer <doc#section> --note ...` for each, "
             "then `craft review` again for round 2.")


def _run_checked(cfg, sys_p, user_p, schema, n, hid, checker) -> dict:
    data = run_referee(cfg, sys_p, user_p, schema, n, hid)
    problems = checker(data)
    if problems:
        data = run_referee(cfg, sys_p + "\n\nYour previous output was rejected: " + "; ".join(problems), user_p, schema, n, hid)
        problems = checker(data)
        if problems:
            raise CraftError("referee output rejected twice: " + "; ".join(problems))
    return data


def _resolve_objection(state: InvestigationState, ref: str) -> tuple[str, str]:
    """`H1:O2`, or a bare `O2` when exactly one hypothesis in review has it open."""
    if ":" in ref:
        hid, oid = ref.split(":", 1)
        return hid, oid
    hits = [h for h, r in state.hypotheses.items() if ref in r.open_blocking]
    if len(hits) == 1:
        return hits[0], ref
    if not hits:
        raise CraftError(f"{ref} is not an open blocking objection on any hypothesis")
    raise CraftError(f"{ref} is open on several hypotheses ({', '.join(hits)}); write it as <H>:{ref}")


@review_app.command("respond")
def review_respond(objection_id: str = typer.Argument(..., help="Objection, e.g. H1:O2 (or O2 when unambiguous)."),
                   pointer: str = typer.Option(..., "--pointer", help="doc#section that changed, e.g. hypotheses/H1.md#criteria"),
                   note: str = typer.Option(..., "--note"), inv_id: Optional[str] = INV_OPT) -> None:
    """File the author's response to a blocking objection (a pointer to the design change)."""
    prog, inv, state = _ctx(inv_id)
    hid, oid = _resolve_objection(state, objection_id)
    rec = state.hypotheses.get(hid)
    if rec is None or not rec.rounds or oid not in rec.rounds[-1].blocking_open:
        open_ = ", ".join(rec.rounds[-1].blocking_open) if rec and rec.rounds else "none"
        raise CraftError(f"{oid} is not an open blocking objection on {hid} (open: {open_})")
    if rec.exhausted:
        raise CraftError(f"{hid}'s review is capped; fix the design and start a new cycle with `craft review --hyp {hid}`")
    rnd = rec.rounds[-1]
    when = now_iso()
    rnd.responses[oid] = {"pointer": pointer, "note": note, "when": when}
    rf = inv.review_responses(hid, rnd.n)
    prior = rf.read_text(encoding="utf-8") if rf.exists() else ""
    _write_record(inv, state, rf, prior + f"## {oid}\n\n- pointer: {pointer}\n- note: {note}\n- when: {when}\n\n")
    state.save(inv.root)
    remaining = [i for i in rnd.blocking_open if i not in rnd.responses]
    echo(f"Response to {hid}:{oid} filed. Remaining unanswered on {hid}: {', '.join(remaining) or 'none'}.")


@review_app.command("show")
def review_show(inv_id: Optional[str] = INV_OPT) -> None:
    """Print each hypothesis's review rounds and registration."""
    prog, inv, state = _ctx(inv_id)
    if not any(r.rounds or r.cycles for r in state.hypotheses.values()):
        echo("No review rounds yet.")
        return
    for hid, rec in state.hypotheses.items():
        for k, cyc in enumerate(rec.cycles, start=1):
            echo(f"{hid} cycle {k}: {len(cyc)} round(s) (review/{hid}/cycle-{k}/)")
        for r in rec.rounds:
            echo(f"{hid} round {r.n} ({r.when}) open blocking: {', '.join(r.blocking_open) or 'none'}; advisory: {', '.join(r.advisory) or 'none'}")
        if rec.registered_at:
            echo(f"{hid} registered at {rec.registered_at} (sha256 {rec.registered_sha256[:12]})")


# ------------------------------------------------------------------ env

@app.command()
def lock(file: Path = typer.Argument(..., help="Lock file to record (uv.lock, requirements.txt, environment.yml)."),
         inv_id: Optional[str] = INV_OPT) -> None:
    """Record the locked environment before the first verdict (replaces the empty initial lock)."""
    prog, inv, state = _ctx(inv_id)
    if state.verdicts:
        raise CraftError("verdicts have been filed against the current environment; changes go through `craft propose package`")
    envlock.init_lock(inv, state, file)
    state.save(inv.root)
    echo(f"env.lock v{state.env.version} recorded (sha256 {state.env.lock_sha256[:12]}).")


@app.command()
def propose(what: str = typer.Argument(..., help="package"), name: str = typer.Argument(..., help="Package (and version) to add."),
            reason: str = typer.Option(..., "--reason"), inv_id: Optional[str] = INV_OPT) -> None:
    """Propose an addition to the locked environment; execution halts until the researcher approves."""
    if what != "package":
        raise CraftError("only `craft propose package <name> --reason ...` exists")
    prog, inv, state = _ctx(inv_id)
    envlock.propose(inv, state, name, reason)
    state.save(inv.root)
    echo(f"Proposed adding '{name}' (env v{state.env.version} -> v{state.env.version + 1}). "
         "Verdicts are halted: no verdicts can be filed until the researcher types `/craft-approve` "
         "(or `/craft-reject --note ...`). End your message with that command on its own line and wait.")


# ------------------------------------------------------------------ verdict

@app.command()
def verdict(experiment: str, criterion: str = typer.Option(..., "--criterion", help="H1:C1 (or C1 when unambiguous), or a kill criterion id like K1."),
            evidence: Path = typer.Option(..., "--evidence", help="Evidence file under experiments/<exp>/evidence/"),
            metric: Optional[str] = typer.Option(None, "--metric", help="Metric key in the evidence file (default: the criterion's metric)."),
            exploratory: list[Path] = typer.Option([], "--exploratory", help="Exploratory dirs/files to link for transparency (never evidence)."),
            seed: list[str] = typer.Option([], "--seed"), data_id: list[str] = typer.Option([], "--data-id"),
            inv_id: Optional[str] = INV_OPT) -> None:
    """Compute a verdict for one criterion from an evidence file, against the registered threshold."""
    prog, inv, state = _ctx(inv_id)
    state.require_untainted("file a verdict")
    if state.phase == Phase.FRAMING:
        raise CraftError("the problem statement has not been approved yet; verdicts come after `/craft-approve` and review.")
    if state.phase == Phase.CLOSING:
        raise CraftError(f"investigation {state.id} is closing (kill criterion {state.kill.criterion} was met); no new verdicts.")
    state.require_phase(Phase.OPEN, action="file a verdict")
    if state.env.pending_proposal:
        raise CraftError(f"verdicts are halted: package proposal '{state.env.pending_proposal['package']}' awaits the researcher's `/craft-approve` (or `/craft-reject --note ...`).")
    pfm, _ = read_doc(inv.problem)
    kills = {k["id"]: k for k in kill_criteria(pfm)}
    if ":" not in criterion and criterion in kills:
        return _kill_check(prog, inv, state, experiment, kills[criterion], evidence, metric, seed, data_id)
    hid, cname = _resolve_criterion(inv, state, criterion, kills)
    key = f"{hid}:{cname}"
    hv = registry.hyp_view(inv, state, hid)
    if not hv.rec.registered_sha256:
        raise CraftError(
            f"{hid} is not registered (status: {hv.status}); verdicts are computed only against criteria that review "
            f"fixed before the data. Run `craft review` first. {registry.blocked_reason(inv, state)}"
        )
    reg_crits = criteria_table(hv.registered_fm)
    if cname not in reg_crits:
        raise CraftError(f"{cname} is not a criterion of {hid} as registered ({', '.join(reg_crits)})")
    crit = reg_crits[cname]
    view = registry.exp_view(inv, state, experiment)
    if view.has_plan and view.exploratory:
        raise CraftError(f"experiment {experiment} is planned as exploratory; exploratory results never back a criterion.")
    if view.has_plan and view.tests and key not in view.tests:
        raise CraftError(f"experiments/{experiment}/plan.md tests {', '.join(view.tests)}, not {key}; an experiment "
                         "backs the criteria its plan named, so plan the experiment for this criterion.")
    ev = _resolve_evidence(inv, experiment, evidence)
    if ev.stat().st_mtime < registry.parse_iso(hv.rec.registered_at):
        raise CraftError(
            f"{inv.rel(ev)} was produced before {hid} was registered ({hv.rec.registered_at}): data that existed before "
            f"the criteria were fixed cannot back them. Move it to experiments/{experiment}/exploratory/ and rerun."
        )
    links = _exploratory_links(inv, experiment, exploratory)
    data = load_evidence(ev)
    m = extract(data, metric or crit["metric"])
    op, thr = crit["op"], float(crit["threshold"])
    label, rationale = label_for(m, op, thr)
    seeds, data_ids = _repro(m, seed, data_id)
    post_hoc = _post_hoc(hv, cname, crit, data, metric)

    killed = None
    for k in kill_criteria(pfm):
        if k["metric"] in _metric_names(data):
            km = extract(data, k["metric"])
            if compare(k["op"], km.point, float(k["value"])):
                killed = (k, km)
                break

    ev_rel = inv.rel(ev)
    vfm = {
        "experiment": experiment, "hypothesis": hid, "criterion": key, "label": label, "rationale": rationale,
        "metric": m.metric, "op": op, "threshold": thr,
        "observed": m.point, "ci95": [m.ci_low, m.ci_high], "n": m.n, "unit": m.unit,
        "uncertainty_source": m.source,
        "evidence": [{"path": ev_rel, "sha256": sha256_file(ev)}],
        "exploratory_links": links,
        "exploratory_note": "linked for transparency; none of these numbers are evidence for any criterion" if links else None,
        "seeds": seeds, "data_ids": data_ids,
        "env_version": state.env.version, "env_lock_sha256": state.env.lock_sha256,
        "hypothesis_registered_sha256": hv.rec.registered_sha256, "hypothesis_registered_at": hv.rec.registered_at,
        "problem_sha256": state.problem_sha256,
        "post_hoc": post_hoc,
        "created": now_iso(),
        "kill_triggered": {"criterion": killed[0]["id"], "condition": killed[0]["condition"], "observed": killed[1].point} if killed else None,
    }
    body = [f"# Verdict — {experiment} / {key}: **{label.upper()}**", "",
            f"Criterion {key} (as registered {hv.rec.registered_at}): {m.metric} {op} {thr} under: {crit.get('conditions')}",
            f"Observed: {m.point:.6g} (95% CI [{m.ci_low:.6g}, {m.ci_high:.6g}], n={m.n}) — {rationale}", "",
            "Evidence: " + ", ".join(f"`{e['path']}` (sha256 {e['sha256'][:12]})" for e in vfm["evidence"]),
            f"Reproducibility: seeds {seeds}; data {data_ids}; env v{state.env.version} ({(state.env.lock_sha256 or '')[:12]}); "
            f"hypothesis {hid} as registered ({hv.rec.registered_sha256[:12]})"]
    if post_hoc:
        body += ["", "POST-HOC: " + post_hoc["note"]]
    if links:
        body += ["", "Exploratory (not evidence): " + ", ".join(f"`{l}`" for l in links)]
    if killed:
        body += ["", f"KILL CRITERION {killed[0]['id']} MET: {killed[0]['condition']} (observed {killed[1].point:.6g}). Execution halted."]
    vpath = inv.verdict(experiment, key)
    _write_record(inv, state, vpath, render_verdict(vfm, body))
    state.record(ev_rel, vfm["evidence"][0]["sha256"])
    rel_v = inv.rel(vpath)
    state.verdicts = [v for v in state.verdicts if not (v.experiment == experiment and v.criterion == key)]
    state.verdicts.append(VerdictRef(experiment=experiment, criterion=key, label=label, file=rel_v, when=now_iso(),
                                     post_hoc=bool(post_hoc and post_hoc.get("changed"))))
    echo(f"Verdict for {key} ({experiment}): {label.upper()} — {rationale}. Written to {rel_v}.")
    if post_hoc:
        echo("POST-HOC: " + post_hoc["note"])
    if killed:
        _route_to_closing(inv, state, killed[0], killed[1].point, ev_rel)
        echo(f"KILL CRITERION {killed[0]['id']} MET ({killed[0]['condition']}; observed {killed[1].point:.6g}). "
             "Remaining experiments are halted; the investigation is routed to closure. Fill closure.md (anomalies -> "
             "open questions), then the researcher types `/craft-close`.")
        return
    state.save(inv.root)
    hv = registry.hyp_view(inv, state, hid)
    left = f"; still untested: {', '.join(hv.untested)}" if hv.untested else ""
    echo(f"{hid} is now {hv.status}{left}. Propose up to three follow-ups grounded in this result (a question in "
         "questions.md, a hypothesis in hypotheses/, or an experiment plan) with "
         f"`derived_from: {rel_v}`, and write the ones the researcher accepts.")


def _resolve_criterion(inv: InvestigationPaths, state: InvestigationState, ref: str, kills: dict) -> tuple[str, str]:
    """`H1:C1`, or a bare `C1` when exactly one registered hypothesis has it."""
    if ":" in ref:
        hid, cname = ref.split(":", 1)
        return hid, cname
    hits = [h.id for h in registry.all_hypotheses(inv, state) if h.rec.registered_sha256 and ref in h.criteria]
    if len(hits) == 1:
        return hits[0], ref
    if not hits:
        raise CraftError(
            f"'{ref}' is neither a criterion of a registered hypothesis (write it as H1:C1) nor a mechanically "
            f"checkable kill criterion in problem.md ({', '.join(kills) or 'none'})"
        )
    raise CraftError(f"'{ref}' is a criterion of several hypotheses ({', '.join(hits)}); write it as <H>:{ref}")


def _post_hoc(hv: registry.HypView, cname: str, reg: dict, data: dict, metric: Optional[str]) -> dict | None:
    """If the criteria were changed after registration, say how, and what the changed criterion would conclude."""
    if not hv.post_hoc:
        return None
    cur = criteria_table(hv.fm).get(cname)
    if cur is None:
        return {"changed": True, "note": f"{cname} was removed from hypotheses/{hv.id}.md after registration. "
                                         "The label above is the pre-registered one."}
    keys = ("metric", "op", "threshold", "conditions")
    diffs = [f"{k} {reg.get(k)!r} -> {cur.get(k)!r}" for k in keys if reg.get(k) != cur.get(k)]
    if not diffs:
        return {"changed": False, "note": f"other criteria or the outcome rule of {hv.id} changed after registration; "
                                          f"{cname} itself is unchanged."}
    out = {"changed": True, "now": {k: cur.get(k) for k in keys}}
    try:
        m2 = extract(data, metric if metric and cur.get("metric") == reg.get("metric") else cur["metric"])
        label2, _ = label_for(m2, cur["op"], float(cur["threshold"]))
        out["label_under_changed_criterion"] = label2
        tail = f" Under the changed criterion this would be {label2.upper()}."
    except (CraftError, KeyError, TypeError, ValueError):
        tail = " The changed criterion cannot be evaluated from this evidence file."
    out["note"] = (f"{hv.id}:{cname} was changed after registration ({'; '.join(diffs)}).{tail} "
                   "The label above is the pre-registered one.")
    return out


def _exploratory_links(inv: InvestigationPaths, experiment: str, exploratory: list[Path]) -> list[str]:
    links = []
    for x in exploratory:
        xr = x.resolve()
        try:
            xr.relative_to(inv.exploratory_dir(experiment).resolve())
        except ValueError:
            raise CraftError(f"--exploratory {x} must be under experiments/{experiment}/exploratory/")
        links.append(inv.rel(xr))
    return links


def _repro(m, seed: list[str], data_id: list[str]) -> tuple[list, list]:
    seeds = seed or (m.seeds if m.seeds else [])
    data_ids = data_id or ([m.data_id] if m.data_id else [])
    if not seeds:
        raise CraftError("no seeds recorded: put `seeds` in the evidence file or pass --seed (reproducibility record)")
    if not data_ids:
        raise CraftError("no data identifier: put `data_id` in the evidence file or pass --data-id")
    return seeds, data_ids


def _route_to_closing(inv: InvestigationPaths, state: InvestigationState, k: dict, observed: float, evidence: str) -> None:
    state.kill.triggered = True
    state.kill.criterion = k["id"]
    state.kill.when = now_iso()
    state.kill.evidence = evidence
    state.kill.observed = observed
    state.phase = Phase.CLOSING
    state.save(inv.root)
    if not inv.closure.exists():
        inv.closure.write_text(_template("closure.md").replace("{id}", state.id), encoding="utf-8")


def _resolve_evidence(inv: InvestigationPaths, experiment: str, evidence: Path) -> Path:
    ev = evidence.resolve()
    try:
        ev.relative_to(inv.evidence_dir(experiment).resolve())
    except ValueError:
        where = "exploratory" if "exploratory" in ev.parts else "outside"
        raise CraftError(
            f"evidence must live under experiments/{experiment}/evidence/. {ev} is {where} that area"
            + (": exploratory numbers are never evidence for a criterion, however good they look." if where == "exploratory" else ".")
        )
    if not ev.exists():
        raise CraftError(f"{ev} does not exist")
    return ev


def _kill_check(prog, inv, state, experiment: str, k: dict, evidence: Path, metric, seed, data_id) -> None:
    """Evaluate one kill criterion from problem.md against an evidence file (Journey 6.5)."""
    ev = _resolve_evidence(inv, experiment, evidence)
    data = load_evidence(ev)
    m = extract(data, metric or k["metric"])
    op, value = k["op"], float(k["value"])
    met = compare(op, m.point, value)
    label = "kill-met" if met else "kill-not-met"
    seeds, data_ids = _repro(m, seed, data_id)
    ev_rel = inv.rel(ev)
    vfm = {
        "experiment": experiment, "criterion": k["id"], "kind": "kill-criterion", "label": label,
        "condition": k.get("condition"), "metric": m.metric, "op": op, "value": value,
        "observed": m.point, "ci95": [m.ci_low, m.ci_high], "n": m.n, "unit": m.unit,
        "uncertainty_source": m.source,
        "evidence": [{"path": ev_rel, "sha256": sha256_file(ev)}],
        "seeds": seeds, "data_ids": data_ids,
        "env_version": state.env.version, "env_lock_sha256": state.env.lock_sha256,
        "problem_sha256": state.problem_sha256,
        "created": now_iso(),
    }
    body = [f"# Kill check — {experiment} / {k['id']}: **{label.upper()}**", "",
            f"Kill criterion {k['id']}: {k.get('condition')}  ({m.metric} {op} {value})",
            f"Observed: {m.point:.6g} (95% CI [{m.ci_low:.6g}, {m.ci_high:.6g}], n={m.n})", "",
            "Evidence: " + ", ".join(f"`{e['path']}` (sha256 {e['sha256'][:12]})" for e in vfm["evidence"]),
            f"Reproducibility: seeds {seeds}; data {data_ids}; env v{state.env.version} ({(state.env.lock_sha256 or '')[:12]})"]
    vpath = inv.verdict(experiment, k["id"])
    _write_record(inv, state, vpath, render_verdict(vfm, body))
    state.record(ev_rel, vfm["evidence"][0]["sha256"])
    rel_v = inv.rel(vpath)
    state.verdicts = [v for v in state.verdicts if not (v.experiment == experiment and v.criterion == k["id"])]
    state.verdicts.append(VerdictRef(experiment=experiment, criterion=k["id"], label=label, file=rel_v, when=now_iso()))
    if met:
        _route_to_closing(inv, state, k, m.point, ev_rel)
        echo(f"KILL CRITERION {k['id']} MET ({k.get('condition')}; observed {m.point:.6g} {op} {value}). Written to {rel_v}. "
             "Remaining experiments are halted; the investigation is routed to closure. Fill closure.md (anomalies -> "
             "open questions), then the researcher types `/craft-close`.")
        return
    state.save(inv.root)
    echo(f"Kill criterion {k['id']} NOT met (observed {m.point:.6g}, kill if {op} {value}). Recorded in {rel_v}; execution continues.")


def _metric_names(data: dict) -> set[str]:
    names = set()
    if isinstance(data.get("metrics"), dict):
        names |= set(data["metrics"].keys())
    if data.get("metric"):
        names.add(data["metric"])
    return names


# ------------------------------------------------------------------ close (human)

@app.command()
def close(inv_id: Optional[str] = INV_OPT, note: str = typer.Option("", "--note"),
          incomplete: bool = typer.Option(False, "--incomplete", hidden=True, help="Accepted for compatibility; closing is always allowed.")) -> None:
    """RESEARCHER ONLY. Close the investigation whenever you choose: outcomes and open threads go to memory, files to the archive."""
    require_human("close")
    echo(_decide(lambda prog: decisions.close(prog, inv_id, note, _tty_confirm, "terminal")))


# ------------------------------------------------------------------ reopen (retired) / resolve (human)

@reopen_app.command("problem")
def reopen_problem(inv_id: Optional[str] = INV_OPT, note: str = typer.Option("", "--note")) -> None:
    """Retired: problem.md stays editable after approval; the researcher re-approves a changed version."""
    echo(decisions.REOPEN_RETIRED)


@reopen_app.command("review")
def reopen_review(inv_id: Optional[str] = INV_OPT, note: str = typer.Option("", "--note")) -> None:
    """Retired: after a capped review, change the hypothesis and `craft review --hyp <id>` starts a new cycle."""
    echo(decisions.REOPEN_RETIRED)


@app.command()
def resolve(inv_id: Optional[str] = INV_OPT, note: str = typer.Option(..., "--note"),
            accept_current: bool = typer.Option(False, "--accept-current", help="Re-record hashes of the current record files (logged).")) -> None:
    """RESEARCHER ONLY. Clear an integrity hold after reviewing what happened."""
    require_human("resolve")
    echo(_decide(lambda prog: decisions.untaint(prog, inv_id, note, accept_current, _tty_confirm, "terminal")))


# ------------------------------------------------------------------ status / explain / decisions / verify

@app.command()
def status(inv_id: Optional[str] = INV_OPT, as_json: bool = typer.Option(False, "--json")) -> None:
    """The board: each investigation's hypotheses, experiments, open questions, and whose turn it is."""
    prog = _prog()
    if as_json:
        out = {}
        for i in prog.list_investigations():
            inv, st = load_context(prog, i)
            out[i] = registry.public(inv, st)
        echo(json.dumps(out, indent=2))
        return
    echo(status_text(prog, inv_id))


@app.command()
def explain(entry_id: str = typer.Argument(..., help="Memory entry id, e.g. F-0001 or R-0002")) -> None:
    """Walk the chain claim -> criterion -> observed -> files, verifying every link resolves."""
    text, broken = explain_text(_prog(), entry_id)
    echo(text)
    if broken:
        raise typer.Exit(code=1)


@app.command("decisions")
def decisions_cmd(inv_id: Optional[str] = INV_OPT) -> None:
    """The researcher's recorded decisions (what they read and approved, and through which channel)."""
    echo(decisions_text(_prog(), inv_id))


@app.command()
def verify() -> None:
    """Integrity of every recorded file: reviews, registrations, verdicts, cited evidence, env.lock, memory, archive."""
    prog = _prog()
    problems = verify_all(prog)
    if problems:
        for p in problems:
            echo(f"- {p}")
        raise typer.Exit(code=1)
    echo("All recorded files intact.")


@app.command(hidden=True)
def hook(event: str = typer.Argument(..., help="pre-tool-use | user-prompt-submit | session-start | stop")) -> None:
    """Claude Code hook entry point (reads the hook JSON on stdin)."""
    fn = hooks.EVENTS.get(event)
    if fn is None:
        raise CraftError(f"unknown hook event '{event}'")
    raise typer.Exit(code=fn())


def main() -> None:
    try:
        code = app(standalone_mode=False)  # click returns a typer.Exit code instead of raising it here
        if isinstance(code, int) and code:
            sys.exit(code)
    except CraftError as e:
        typer.echo(f"craft: {e}", err=True)
        sys.exit(e.exit_code)
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except typer.Abort:
        sys.exit(1)


if __name__ == "__main__":
    main()
