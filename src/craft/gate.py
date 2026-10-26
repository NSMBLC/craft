"""The gate: may the *agent* perform this write right now?

Pure decision logic shared by the Claude Code hook and the CLI's own checks.
Everything the researcher's own code/data touches outside CRAFT-managed paths is allowed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .paths import ARCHIVE_DIR, INVESTIGATIONS_DIR, MEMORY_DIR, PROGRAMME_MARKER, InvestigationPaths, Programme
from .state import InvestigationState, Phase
from .util import CraftError

HUMAN_ONLY = ("approve", "reject", "close", "reopen", "resolve", "correct")  # `craft <verb> ...`
# The verb must be the subcommand (`craft approve`, `uv run craft close`, `python -m craft.cli resolve`),
# not a word in a quoted reason or limitation text. The CLI also refuses these inside an agent tool
# call (human.require_human), so this screen is one layer of three.
HUMAN_ONLY_RE = re.compile(
    r"\bcraft(?:\.cli)?['\"]?\s+['\"]?(approve|reject|close|reopen|resolve|correct|hook)\b"
    r"|\bCRAFT_ALLOW_NON_TTY\b|\bCRAFT_HUMAN\b"
    r"|\buser-prompt-submit\b|\bhooks\.py\b|\bcraft\.hooks\b|\bcraft\.decisions\b|\bdecisions\.py\b"
)
# Not file writes: `2>&1`, `>&2`, `&>/dev/null`, `>/dev/null`, `2>/dev/null`, an email in angle
# brackets (`<name@host>` in commit trailers), and `->` / `=>` arrows in prose.
HARMLESS_REDIRECT_RE = re.compile(
    r"\d*>&\d+|&>\s*/dev/null|\d*>{1,2}\s*/dev/null|<[^<>\s]+@[^<>\s]+>|[-=]>"
)
# A file-open mode that writes (w, a, x or +), as a whole quoted string: only the mode argument counts,
# never a path that happens to start with "a" or "w" (open('archive/...') is a read).
_WRITE_MODE = r"""['"][rbt]*[wax+][rwabxt+]*['"]"""
MUTATION_RE = re.compile(
    r"(?<![<>])>{1,2}(?!>)|(?<!-)\btee\b|(?<!-)\bmv\b|(?<!-)\bcp\b|(?<!-)\brm\b|\bchmod\b|\bchown\b|\bsed\s+-[a-zA-Z]*i|"
    r"\btruncate\b|(?<!-)\bln\b|\bmkdir\b|\brmdir\b|\bpatch\b|\bgit\s+(checkout|restore|reset|clean|stash)\b|"
    rf"\bopen\([^)]*?,\s*(?:mode\s*=\s*)?{_WRITE_MODE}|\.open\(\s*(?:mode\s*=\s*)?{_WRITE_MODE}|"
    r"\bwrite_text\b|\bwrite_bytes\b|\bshutil\b|\bos\.(remove|unlink|rename|replace|chmod)\b|\bunlink\b"
)


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
    checkpoint: str = ""

    @staticmethod
    def ok() -> "Decision":
        return Decision(True)

    @staticmethod
    def deny(reason: str, checkpoint: str = "") -> "Decision":
        return Decision(False, reason, checkpoint)


def _load_state(prog: Programme, inv_id: str) -> InvestigationState | None:
    try:
        return InvestigationState.load(prog.investigation_dir(inv_id))
    except CraftError:
        return None


def decide_write(prog: Programme, target: Path) -> Decision:
    """Decide whether the agent may write/edit/delete `target` (absolute or relative to cwd)."""
    rel = prog.relpath(target if target.is_absolute() else Path.cwd() / target)
    if rel is None:
        return Decision.ok()  # outside the programme: not ours to police
    parts = PurePosixPath(rel.as_posix()).parts
    if not parts:
        return Decision.ok()
    head = parts[0]

    if head == PROGRAMME_MARKER or head == ".claude":
        return Decision.deny(
            f"{rel} is researcher-owned configuration (hooks and rules). The agent may not modify it; "
            "ask the researcher to edit it in their own editor."
        )
    if head == MEMORY_DIR:
        return Decision.deny(
            f"{rel}: institutional memory accepts entries only through the closing of an investigation "
            "(the researcher types `/craft-close`). Record the result as a verdict and let the "
            "investigation close instead.",
            "5.6",
        )
    if head == ARCHIVE_DIR:
        return Decision.deny(f"{rel}: archived investigations are the record of what happened; they are never edited.")
    from . import data as data_mod

    held = data_mod.covering(prog, rel.as_posix())
    if held:
        return Decision.deny(
            f"{rel} is recorded input data ('{held[1]}' in {held[0]}); criteria depend on it, so it is never changed in "
            "place. Write a new snapshot elsewhere and record it under a new id (`craft data add <path> --id <new-id>`)."
        )
    if head != INVESTIGATIONS_DIR:
        return Decision.ok()
    if len(parts) < 2:
        return Decision.ok()  # creating the investigations dir itself
    inv_id = parts[1]
    inner = PurePosixPath(*parts[2:]) if len(parts) > 2 else PurePosixPath()
    state = _load_state(prog, inv_id)
    if state is None:
        # Not a CRAFT investigation yet (or state.json missing) — only `craft new` creates these.
        if inner.name == "state.json" or not inner.parts:
            return Decision.deny(
                f"investigations are created with `craft new {inv_id} --topic ...`, not by writing files."
            )
        return Decision.deny(
            f"{rel}: no investigation '{inv_id}' exists. Create it with `craft new` first."
        )
    return decide_investigation_write(state, inner, InvestigationPaths(prog.investigation_dir(inv_id)))


def decide_investigation_write(state: InvestigationState, inner: PurePosixPath,
                               inv: InvestigationPaths | None = None) -> Decision:
    """Gate table for paths inside an investigation.

    Plans (problem, hypotheses, experiment plans, literature, questions, closure, notes, code) are
    the agent's to write until the investigation closes. Records of what happened (state, reviews,
    registered snapshots, verdicts, cited evidence, env.lock) are written only by `craft`.
    Evidence may be produced only for hypotheses that review has registered.
    """
    name = inner.as_posix()
    ph = state.phase
    inv_id = state.id

    if ph == Phase.CLOSED:
        return Decision.deny(f"investigation {inv_id} is closed; it is the record of what happened.")

    if name == "state.json":
        return Decision.deny("state.json is written only by `craft`; use the corresponding command.")

    if inner.parts and inner.parts[0] == "review":
        if inner.name == "registered.md":
            return Decision.deny(
                f"{name} is the hypothesis exactly as review registered it. Edit hypotheses/{inner.parts[1] if len(inner.parts) > 2 else '<id>'}.md "
                "instead: changes to criteria after registration are allowed and recorded as post-hoc in every verdict.",
                "5.5",
            )
        if re.fullmatch(r"round-\d+\.(json|prompt\.md|hypothesis\.md)", inner.name):
            return Decision.deny(
                "review files are written only by the referee (`craft review`). The agent "
                "never authors or edits a review.",
                "4.1",
            )
        return Decision.deny("the review directory is managed by `craft review` (responses: `craft review respond`).")

    if name == "env.lock":
        return Decision.deny(
            "env.lock changes only through `craft propose package` (agent) followed by "
            "`/craft-approve` (researcher).",
            "6.1",
        )
    if name == "env.proposal.yaml":
        return Decision.deny("package proposals are written with `craft propose package`.")

    if inner.parts and inner.parts[0] == "experiments" and len(inner.parts) >= 3:
        exp = inner.parts[1]
        if re.fullmatch(r"verdict-.*\.md", inner.name) and len(inner.parts) == 3:
            return Decision.deny(
                "verdicts are computed by `craft verdict` from the registered criteria and an evidence "
                "file; the agent never writes a label.",
                "6.2",
            )
        if inner.parts[2] == "evidence":
            if name in state.records:
                return Decision.deny(
                    f"{name} is the evidence a verdict cites; records of what happened are never edited (sha256 "
                    "recorded in state.json). Produce new evidence in a new file, or plan a new experiment.",
                    "6.2",
                )
            return _evidence_write(state, exp, inv)
    if name in state.records:
        return Decision.deny(f"{name} is a record `craft` wrote; it is never edited (sha256 recorded in state.json).")
    return Decision.ok()


def _evidence_write(state: InvestigationState, exp: str, inv: InvestigationPaths | None) -> Decision:
    if state.phase == Phase.FRAMING:
        return Decision.deny(
            "no evidence before the problem statement is approved: the researcher types `/craft-approve`, "
            "then evidence is produced for registered hypotheses (or kill-criterion pilots).",
            "5.1",
        )
    if state.phase == Phase.CLOSING:
        return Decision.deny(
            f"investigation {state.id} is closing (kill criterion {state.kill.criterion} was met); no new evidence is accepted."
        )
    if inv is None:
        return Decision.ok()
    from . import registry

    plan = inv.experiment_plan(exp)
    if not plan.exists():
        return Decision.ok()  # unplanned evidence (e.g. a kill-criterion pilot); `craft verdict` checks it
    view = registry.exp_view(inv, state, exp)
    if view.exploratory:
        return Decision.deny(
            f"experiment {exp} is planned as exploratory: its results go in experiments/{exp}/exploratory/, "
            "which can never back a criterion.",
            "6.3",
        )
    for hid in dict.fromkeys(t.split(":")[0] for t in view.tests):
        hv = registry.hyp_view(inv, state, hid)
        if hv.rec.registered_sha256:
            continue
        if hv.status == "in review":
            last = hv.rec.rounds[-1]
            missing = [o for o in last.blocking_open if o not in last.responses]
            return Decision.deny(
                f"experiment {exp} tests {hid}, which is not registered: review round {len(hv.rec.rounds)} left blocking "
                f"objections open ({', '.join(last.blocking_open)}). Answer each with `craft review respond` "
                f"({', '.join(missing) or 'all answered'} remaining) and request the next round; evidence is "
                "produced once review registers it.",
                "5.2",
            )
        if hv.status == "dropped":
            return Decision.deny(f"experiment {exp} tests {hid}, which is dropped or has no file; update the plan's tests.")
        return Decision.deny(
            f"experiment {exp} tests {hid}, which has not been reviewed: it is a draft. Complete it, run "
            "`craft review`, and produce evidence once review registers it (criteria fixed before data). "
            f"Exploratory runs may go in experiments/{exp}/exploratory/ now.",
            "5.1",
        )
    return Decision.ok()


# ---------------------------------------------------------------- bash screening

_SEPARATORS = {";", "&&", "||", "|", "&", "\n"}
_COPY_PROGRAMS = {"cp", "rsync"}  # read every source, write only the destination


_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "{", "(", "!", "sudo", "command", "env", "time", "nice"}
_REDIRECT = re.compile(r"\d*>{1,2}|&>")


def _copy_dest(words: list[str]) -> str:
    """The destination of a `cp`/`rsync` argument list: `-t DIR`, or the last operand."""
    args, dest, skip = [], None, False
    for i, t in enumerate(words):
        if skip:
            skip = False
            continue
        if t in ("-t", "--target-directory") and i + 1 < len(words):
            dest, skip = words[i + 1], True
        elif t.startswith("--target-directory="):
            dest = t.split("=", 1)[1]
        elif _REDIRECT.fullmatch(t) or t == "<":
            skip = True
        elif not t.startswith("-"):
            args.append(t)
    return dest or (args[-1] if args else "")


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_PYTHONS = re.compile(r"python(3(\.\d+)?)?")


def _split_heredocs(command: str) -> tuple[str, dict[str, str]]:
    """Take each here-document's text out of the command, leaving a placeholder word where it was fed in."""
    lines, out, bodies, i = command.split("\n"), [], {}, 0
    while i < len(lines):
        line, pending = lines[i], []

        def repl(m: re.Match) -> str:
            key = f"__craft_heredoc_{len(bodies) + len(pending)}__"
            pending.append((key, m.group(2)))
            return f" {key} "

        out.append(_HEREDOC_RE.sub(repl, line))
        i += 1
        for key, delim in pending:
            body = []
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i])
                i += 1
            i += 1  # the delimiter line
            bodies[key] = "\n".join(body)
    return "\n".join(out), bodies


_RUNS_TEXT = re.compile(r"\b(?:bash|sh|zsh|python[\d.]*|node|ruby|perl|craft)\b")


def _executed_text(command: str) -> str:
    """The command with the text of here-documents that are only data (`cat <<EOF`) left out; a
    here-document fed to a shell or an interpreter is kept, since it runs."""
    stripped, bodies = _split_heredocs(command)
    keep = []
    for line in stripped.split("\n"):
        for key in re.findall(r"__craft_heredoc_\d+__", line):
            if _RUNS_TEXT.search(line.split(key)[0]):
                keep.append(bodies[key])
    return "\n".join([stripped, *keep])


def _python_code(words: list[str], bodies: dict[str, str]) -> str | None:
    """The program text of `python -c CODE` or `python - <<EOF`, or None for any other command."""
    if not words or not _PYTHONS.fullmatch(PurePosixPath(words[0]).name):
        return None
    if "-c" in words[:-1]:
        return words[words.index("-c") + 1]
    return next((bodies[w] for w in words if w in bodies), None)


def _write_candidates(command: str, base: Path) -> list[tuple[str, Path]]:
    """(token, directory it resolves against) for every file the command may write.

    Each part of the command (split at `;`, `&&`, `||`, `|`) is judged on its own: a part that does not
    write (`ls`, `cd`, a `for ... in` list, `grep`) names no write target, and `cd` only moves the base.
    `cp`/`rsync` (also after `do`, `xargs` or `find -exec`) write only their destination. A writing part
    whose target is a loop variable or comes from `xargs` cannot be read from its own words, so then
    every path in the command counts, as it always did. Inline Python (`-c` or a here-document) is read
    from its syntax tree (pyscan); a shell here-document is screened as a command; any other
    here-document is text."""
    from . import pyscan

    command, bodies = _split_heredocs(command)
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return [(t, base) for t in command.split()]
    out: list[tuple[str, Path]] = []
    seg: list[str] = []
    opaque = False  # a write whose target is not in its own words
    for tok in tokens + [";"]:
        if tok not in _SEPARATORS:
            seg.append(tok)
            continue
        redirects = [seg[i + 1] for i, t in enumerate(seg[:-1]) if _REDIRECT.fullmatch(t)]
        out += [(t, base) for t in redirects]
        words = [t for t in seg if not re.fullmatch(r"\w+=.*", t)]  # leading VAR=value assignments
        while words and words[0] in _KEYWORDS:
            words = words[1:]
        if words[:2] == ["uv", "run"]:
            words = words[2:]
        code = _python_code(words, bodies)
        if code is not None:
            found = pyscan.write_targets(code)
            out += [(t, base) for t in (found if found is not None else code.split())]
            seg = []
            continue
        if words and PurePosixPath(words[0]).name in ("bash", "sh", "zsh") and any(w in bodies for w in words):
            out += _write_candidates(next(bodies[w] for w in words if w in bodies), base)
            seg = []
            continue
        words = [w for w in words if w not in bodies]
        piped = False  # xargs appends its input after the words, unless -I places it
        if words and words[0] == "xargs":
            piped, words = True, words[1:]
            while words and words[0].startswith("-"):
                if words[0] == "-I" or words[0].startswith("-I"):
                    piped = False
                words = words[2:] if words[0] in ("-I", "-n", "-P", "-L", "-d", "-s") else words[1:]
        prog_name = PurePosixPath(words[0]).name if words else ""
        if prog_name == "find" and any(w in ("-exec", "-execdir") for w in words):
            i = next(i for i, w in enumerate(words) if w in ("-exec", "-execdir"))
            body = [w for w in words[i + 1:] if w not in ("{}", "+")]
            if body and PurePosixPath(body[0]).name in _COPY_PROGRAMS:
                out.append((_copy_dest(body[1:]), base))
            elif MUTATION_RE.search(" ".join(body)):
                opaque = True
        elif prog_name == "cd":
            target = words[1] if len(words) > 1 else ""
            if target and not target.startswith(("-", "$", "~")):
                base = Path(target) if Path(target).is_absolute() else base / target
        elif prog_name in _COPY_PROGRAMS:
            dest = _copy_dest(words[1:])
            if (piped and "-t" not in words and not any(w.startswith("--target-directory") for w in words)) or dest.startswith("$"):
                opaque = True
            out.append((dest, base))
        elif MUTATION_RE.search(HARMLESS_REDIRECT_RE.sub(" ", " ".join(w for w in words if not _REDIRECT.fullmatch(w)
                                                                       and w not in redirects))):
            if piped or any("$" in w for w in words[1:]):
                opaque = True
            out += [(t, base) for t in words]
        seg = []
    if opaque:
        out += [(t, base) for t in tokens if t not in _SEPARATORS and t not in bodies]
    return [(t, b) for t, b in out if t]


def decide_bash(prog: Programme, command: str, cwd: Path | None = None) -> Decision:
    """Screen a shell command the agent wants to run.

    Two rules: (1) human-only `craft` subcommands are never the agent's to run;
    (2) if the command looks like it mutates files, every path-like token that resolves into
    the programme is put through the write gate.
    This is a heuristic layer; recorded hashes (`craft verify`) are the backstop.
    """
    if HUMAN_ONLY_RE.search(_executed_text(command)):
        return Decision.deny(
            "that `craft` command is a researcher decision (approve / reject / close / reopen / resolve / correct). "
            "Ask the researcher to type it as a slash command (e.g. `/craft-approve`); "
            "CRAFT executes typed decisions directly. The agent cannot approve on their behalf.",
            "1.6",
        )
    mutation = MUTATION_RE.search(HARMLESS_REDIRECT_RE.sub(" ", command))
    if not mutation:
        return Decision.ok()
    seen: set[str] = set()
    for tok, base in _write_candidates(command, cwd or Path.cwd()):
        tok = tok.strip("'\"`;,()")
        if not tok or tok.startswith("-") or "=" in tok and not ("/" in tok or tok.endswith(".md")):
            continue
        if "/" not in tok and not tok.endswith((".md", ".json", ".yaml", ".lock")):
            continue
        cand = tok.split("=", 1)[1] if "=" in tok else tok
        p = Path(cand)
        p = p if p.is_absolute() else base / p
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        d = decide_write(prog, p)
        if not d.allow:
            return Decision.deny(
                f"(shell) {d.reason} [the command looked like a write because of `{mutation.group(0)}` and "
                f"mentions `{tok}`; if it does not write that file, rephrase the command]",
                d.checkpoint,
            )
    return Decision.ok()
