# CRAFT

Disciplined computational research inside a GenAI session.

CRAFT keeps a research programme honest without making it linear. An investigation holds a
one-page problem statement and a growing registry of hypotheses, experiments, literature and
parked questions. You, the agent, or the results themselves can add a hypothesis at any point;
ideas can be parked for later; the literature can be searched again whenever you like.
Everything you *plan* stays editable.

Two things are enforced *mechanically*: a hypothesis's criteria are registered by an
independent referee before its data exist, and the record of what happened (reviews,
verdicts, the evidence they cite, memory, the archive) is never edited. So the agent cannot
produce evidence for a hypothesis nobody reviewed, cannot relabel a verdict, and cannot write
to memory except by closing an investigation. Changing a threshold after the data is allowed,
but it is never hidden: the verdict keeps the pre-registered label and says what the change
would conclude, and memory tags it post-hoc. The guarantees come from hooks and recorded
hashes (which survive git clones, unlike file permissions), not from the model's good intentions.

The spec is the nine user journeys in `docs/journeys.md`; every numbered checkpoint maps to a
test in `tests/acceptance/checkpoints.md`.

## Install (once per machine)

```
uv tool install git+https://github.com/NSMBLC/craft     # or: uv tool install -e . from a checkout
craft --help
```

Requires Python 3.12+ and, for the independent referee, the `claude` CLI on PATH (or set
`referee.backend: command` in `craft.yaml` to use any other model CLI). The referee uses your
Claude login: an `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` in your environment is ignored
unless you set `referee.use_api_key: true`, in which case `craft review` says it is billing that key.

## Set up a programme (once per research programme)

```
mkdir ~/research/scaling-study && cd ~/research/scaling-study && git init
craft init
git add -A && git commit -m "craft init"
claude            # open Claude Code here from now on
```

`craft init` creates `craft.yaml`, `memory/`, `archive/`, `investigations/`, and installs the
Claude Code adapter: `.claude/settings.json` (hooks + deny rules), a `CLAUDE.md` block with the
agent playbook, and the `/craft` slash commands. It never overwrites files you already have. Run it
again in an existing programme after upgrading CRAFT: it refreshes the playbook block and the slash
commands, and leaves your own text alone.

## Every day

Talk to the agent in plain language: "park that as an idea", "let's test H2 next", "search the
literature again for X", "plan an experiment at 2M params", "H4 waits on the H8 result", "record the
price snapshot before anything runs", "that question was answered by exp4", "note on that verdict that
it only holds in simulation". It writes the files and runs
`craft recall`, `craft new`, `craft validate`, `craft literature add`, `craft review`,
`craft verdict` and so on, and after every result it suggests up to three follow-ups. You read
one-page artifacts and make five kinds of decisions as slash commands in the session (they
autocomplete; the plain `craft ...` forms also work typed as a message or in a terminal of your own):

```
/craft-approve            # approve what the agent is waiting on: the one-page statement, or a package
/craft-reject --note "…"  # refuse a proposed package
/craft-close              # close whenever you choose; memory is written here only
/craft-resolve --note "…" # clear an integrity hold
/craft-correct <id> --note "…"  # correct a memory entry that turned out wrong (shown with it everywhere)
/craft-status  /craft-help  /craft-decisions  /craft-explain <id>   # answered directly, no model turn
```

`/craft-status` is the board: every hypothesis (draft, in review, registered, supported, refuted,
inconclusive), every experiment (planned, run, done; an exploratory one counts as run once it has
output), what each is waiting on, the open and answered questions, the recorded input data, and whose
turn it is.

The record stays true after the fact, too. A limitation found after a verdict is attached to it
(`craft limitation`) without changing its label, and travels with it into memory. Input data that criteria
depend on is recorded by hash (`craft data add`), so a changed snapshot is caught. A memory entry that
turned out wrong is corrected by you with `/craft-correct`; the entry stays as written and the correction
is shown wherever it is.

Typed as a slash command or message, the decision never reaches the model: Claude Code hands every prompt to
CRAFT's UserPromptSubmit hook first, which executes the decision and tells the model the outcome.
The agent cannot do this itself: the hook denies it invoking `craft hook` or any approval command,
the CLI refuses inside an agent tool call, and the terminal form needs an interactive TTY.

## Layout of a programme

```
craft.yaml                     memory/findings.jsonl  refuted.jsonl  open-questions.jsonl
                               answered-questions.jsonl  exploratory.jsonl  corrections.jsonl
investigations/<id>/           problem.md  questions.md  literature/  env.lock  closure.md
  hypotheses/H1.md H2.md …     one per hypothesis; an idea is a file with just a claim
  experiments/<exp>/           plan.md  evidence/  exploratory/  verdict-H1-C1.md (+ .limitations.md)
  review/H1/                   round-<n>.json  round-<n>.prompt.md  registered.md   (records)
archive/<id>/                  closed investigations, intact; hashes checked by `craft verify`
```

## Development

```
uv sync
uv run pytest                                  # unit + acceptance (Journeys 1-8 arc, Journey 9), fake referee
CRAFT_REAL_REFEREE=1 uv run pytest -k real_referee -s   # runs the real referee via claude -p
```
