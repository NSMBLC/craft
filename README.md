# CRAFT

Disciplined computational research inside a GenAI session.

CRAFT turns a research programme into a sequence of gated artifacts, problem statement,
literature map, pre-registered hypothesis, independent review, computed verdicts, closure into
institutional memory, and enforces the gates *mechanically*: the agent operating the session
cannot write a task list before review concludes, cannot edit a frozen hypothesis, cannot
lower a threshold after the data arrive, and cannot write to the programme's memory except by
closing an investigation. Those refusals come from hooks and file permissions, not from the
model's good intentions, so the researcher cannot talk their way past them either.

The spec is the seven user journeys in `docs/journeys.md`; every numbered checkpoint maps to a
test in `tests/acceptance/checkpoints.md`.

## Install (once per machine)

```
uv tool install git+https://github.com/NSMBLC/craft     # or: uv tool install -e . from a checkout
craft --help
```

Requires Python 3.12+ and, for the independent referee, the `claude` CLI on PATH (or set
`referee.backend: command` in `craft.yaml` to use any other model CLI).

## Set up a programme (once per research programme)

```
mkdir ~/research/scaling-study && cd ~/research/scaling-study && git init
craft init
git add -A && git commit -m "craft init"
claude            # open Claude Code here from now on
```

`craft init` creates `craft.yaml`, `memory/`, `archive/`, `investigations/`, and installs the
Claude Code adapter: `.claude/settings.json` (hooks + deny rules), a `CLAUDE.md` block with the
agent playbook, and a `/craft` skill. It never overwrites files you already have.

## Every day

Talk to the agent in plain language. It runs `craft recall`, `craft new`, `craft validate`,
`craft lit add`, `craft review request`, `craft verdict` and so on. You read one-page artifacts
and make five kinds of decisions, each in a terminal of your own, outside the Claude Code session
(commands typed with `!` inherit the agent's environment and are refused):

```
craft approve problem     # after reading the one-page statement
craft env approve         # accept a proposed package addition
craft close               # close the investigation; memory is written here only
craft reopen <problem|review>
craft untaint
```

The agent cannot run these: the hook denies them, the CLI refuses inside an agent tool call,
and they need an interactive terminal. Keep a second terminal open in the programme directory.

## Layout of a programme

```
craft.yaml                     memory/findings.jsonl  refuted.jsonl  open-questions.jsonl
investigations/<id>/           problem.md  hypothesis.md  literature/  review/  tasks.md
                               env.lock  experiments/<exp>/{evidence,exploratory}/  verdict-*.md
archive/<id>/                  closed investigations, intact and read-only
```

## Development

```
uv sync
uv run pytest                                  # unit + scripted acceptance arc (fake referee)
CRAFT_REAL_REFEREE=1 uv run pytest -k real_referee -s   # runs the real referee via claude -p
```
