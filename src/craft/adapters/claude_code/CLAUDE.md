<!-- craft:begin -->
# CRAFT — how research is done in this programme

This repository is a CRAFT research programme. You (the agent) operate the `craft` CLI and write the
planning files; the researcher decides. Research here is not linear: hypotheses, experiments,
literature and questions are added, parked, dropped and revisited as results arrive.

## The hard rules
1. A hypothesis's criteria are fixed by review before its data exist; evidence is produced only for
   registered hypotheses. Exploratory output never backs a criterion.
2. The record of what happened (reviews, registrations, verdicts, cited evidence, recorded data,
   `env.lock`, memory, the archive) is never edited. When a write is refused, relay the reason
   verbatim, state the rule, and offer the legitimate path. Never route around a refusal.
3. Decisions are the researcher's: approving, rejecting, closing, resolving a hold, correcting memory,
   and deferring a hypothesis. They type the slash commands; you never run those commands, never
   suggest `!`, and never set `deferred:` on your own initiative.
4. Memory is written only by closing. Never write findings directly.
5. Never write "no prior work addresses this"; name the closest prior work and the delta.

## Where things are
Plans are files you write: `problem.md`, `hypotheses/H<n>.md` (an idea is just a `claim:` line),
`experiments/<name>/plan.md` (`tests: [H1:C1]` or `exploratory: true`), `questions.md` (one bullet
per question), `literature/`. Start each from its template or from what `craft validate` asks for; give
every hypothesis and plan `origin:` and `derived_from:` (what prompted it). Statuses are derived: read
them on the board (`craft status`). What each word means, and what happens to it at closure:
`craft glossary`. Field-level detail comes from the validator and the command messages when it matters:
follow them, and fix everything a refusal lists before retrying.

## The workflow
1. **Framing.** Run `craft recall "<the researcher's words>"` before drafting anything. If it returns a
   refuted or existing entry, cite it and ask what has changed; then `craft new <id> --topic "..."`
   (with `--acknowledge <entry> --justification "..."` for each). Choose the id yourself; never ask the
   researcher for bookkeeping. Interview about readers, not methods: who changes their mind, what they
   do differently, and the kill criteria; propose defaults for scope and metric. Fill `problem.md` in
   place (studying X, to find out Y, so that a named reader understands Z; the cost of not answering;
   one page). **Kill criteria** say when the question is dead or unanswerable ("the baseline cannot be
   reproduced within 2%", "pilot spread is too large to detect the effect"), never success ("if A is
   20% faster we stop" is optional stopping). Run `craft validate problem`; if the researcher brought
   their own statement, report only what is missing. Then ask them to type `/craft-approve`.
2. **Literature**, any time: `craft literature add` with `--fulltext` only for sources you read in
   full, otherwise `--abstract-only` or `--rejected` with a reason. Name the closest prior work with
   `craft literature closest`. Search again whenever a result calls for it.
3. **Hypotheses.** Park ideas freely; flesh out the one the researcher picks; `craft validate H<n>` and
   report its result honestly.
4. **Review.** `craft review` sends every complete draft to an independent referee. Answer each
   blocking objection by changing the design, `craft review respond H1:O1 --pointer ... --note ...`,
   then `craft review` again. Two rounds at most; after that only a genuine change starts a new cycle.
   A clean pass registers the hypothesis.
5. **Experiments.** Write the plan before running. Record the input data criteria depend on
   (`craft data add`) and the environment (`craft lock <lock file>`) before the first verdict; a new
   package is `craft propose package <pkg> --reason ...`, then stop until the researcher decides.
   Judge each criterion with `craft verdict <exp> --criterion H1:C1 --evidence <file>`, and kill
   criteria the same way (`--criterion K1`). A met kill criterion halts everything: stop and report.
6. **After every verdict or new source, suggest** up to three follow-ups (a question, hypothesis or
   experiment) with `derived_from:` pointing at what prompted them. Write only the ones the researcher
   accepts.
7. **Closure** is the researcher's choice: fill `closure.md`, then ask them to type `/craft-close`.

## Keeping the record true
- A limitation found after a verdict: `craft limitation <exp> --criterion H1:C1 --text ... --source ...`
  (`--question` if it settles a parked one). The label never changes.
- A parked question that was answered: add `answered: <pointer>` to its bullet.
- A memory entry that turned out wrong: show the researcher the entry and the evidence, and give them
  `/craft-correct <entry-id> --note "..." --evidence <file>` to type.
- A threshold changed after the data: allowed if the researcher insists, but say plainly that the
  verdict keeps the pre-registered label, shows what the change would conclude, and memory tags it
  post-hoc. Offer the confirmatory path: a new hypothesis tested on new data.

## Asking for a decision
When the next step is the researcher's, end your message with the exact slash command on its own line,
as `craft status` shows it (with `--inv <id>` when it says so). They can also type `/craft-status`,
`/craft-help`, `/craft-glossary`, `/craft-decisions` and `/craft-explain <id>`; CRAFT answers those in a
`<craft-info>` block, which you show verbatim. A `<craft-decision>` block reports a decision CRAFT
already executed: report it and follow its next-step line.
<!-- craft:end -->
