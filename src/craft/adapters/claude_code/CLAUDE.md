<!-- craft:begin -->
# CRAFT — how research is done in this programme

This repository is a CRAFT research programme. You (the agent) operate the `craft` CLI and write
the planning files; the researcher decides. Research here is not linear: hypotheses, experiments,
literature and questions are added, parked, dropped and revisited as results arrive. Two things are
fixed: a hypothesis's criteria are fixed by review *before* its data exist, and the record of what
happened (reviews, verdicts, cited evidence, memory, archive) is never edited. Hooks enforce both;
when a write is refused, relay the reason verbatim, state the rule, and offer the legitimate path.
Never route around a refusal (no shell redirects, no editing state.json or settings).

## The files (all editable by you until the investigation closes)

- `problem.md`: the one-page question. Approved by the researcher; if it changes later, they re-approve it.
- `hypotheses/H<n>.md`: one per hypothesis. An **idea** is just a file with a `claim:` line
  (`craft validate` accepts it as an idea; `--full` lists what a draft needs); a full draft adds warrant,
  criteria, outcome rule, two or more rivals with discriminators, predictions and a power check. Fill in
  `origin: researcher|agent` and `derived_from:` (the verdict file, experiment, `lit:<key>` or question
  that prompted it). To drop one, set `dropped: <reason>`. When the researcher decides to hold a
  registered hypothesis back (it stays registered and closes as an open question), set
  `deferred: <reason>`; never set it on your own initiative. A criterion whose metric has no spread (exact
  computation on fixed inputs) says `deterministic: <why>` before review; evidence never declares it. If
  the outcome rule is exactly "all supported -> supported, any refuted -> refuted, else inconclusive",
  set `outcome_rule.mechanical: true`; otherwise CRAFT's label is shown as a roll-up next to the rule.
  Write each outcome branch as a condition in words, not a pointer to another branch: it is quoted next to the label.
- `experiments/<name>/plan.md`: `description:` and `tests: [H1:C1, H2]` (or `exploratory: true`),
  plus `origin`/`derived_from`; `abandoned: <reason>` to stop one. Status (planned, run, done) is derived;
  an exploratory experiment counts as run once `exploratory/` has output.
- `questions.md`: parked questions, one `- ` bullet each. When one is answered, add
  `answered: <pointer>` (the verdict, experiment or source that answered it) to its bullet.
- `literature/`: open at all times; new searches are welcome whenever results raise new questions.

## The workflow

1. **Framing**: before drafting anything, run `craft recall "<the researcher's words>"`. If it
   returns a refuted or existing entry, cite it and ask what has changed; only then run
   `craft new <id> --topic "..." --acknowledge <entry-id> --justification "..."`.
   Choose the investigation id yourself (short kebab-case slug, e.g. `kmeanspp-init-cost`);
   never ask the researcher for bookkeeping. Then interview them about *readers*, not
   methods: who changes their mind if this is answered, and what do they do differently? Do
   not accept "it would be good to know". Ask the three questions the statement cannot exist
   without (reader, what they do differently, kill criteria); for scope and metric, propose
   defaults for the researcher to correct rather than asking open-ended.
   `craft new` creates `problem.md` from a template; fill that file in place (the write is
   expected, do not ask whether to overwrite it). Fill it in the three-clause shape (studying X, to find out Y, so that a named
   reader understands Z) with the cost of leaving it unanswered and at least one kill
   criterion (prefer metric/op/value so it can be checked mechanically). Keep it to one page.

   **Kill criteria** are conditions under which the question turns out to be dead or
   unanswerable, so the investigation is abandoned *before* the budget is spent. They are
   never success conditions. Correct examples: "the baseline cannot be reproduced within 2%
   of its published number"; "pilot run-to-run standard deviation exceeds 0.5, so the planned
   runs cannot detect the effect"; "the target regime does not fit on available hardware".
   Wrong example: "if A is 20% faster we stop" — that is a success criterion; stopping on a
   favourable result is optional stopping, which pre-registration exists to prevent.
   Run `craft validate problem`. If the researcher brings their own statement, validate it and
   report only what is missing; do not rewrite what is sound and do not re-interview.
   Then stop and tell the researcher: "Type `/craft-approve` when you have read it." That typed message is executed by CRAFT's prompt hook, not by you; you will see a
   `<craft-decision>` block with the outcome. Never run approval commands yourself, and never
   suggest `!`. Nothing advances before the approval.
2. **Literature**: `craft literature add <key> --title ... --fulltext <path> --claims ... --method ...
   --relation supports|conflicts|orthogonal --does-not-cover ...` only for sources whose full
   text you actually retrieved and read. Anything seen only as an abstract goes in with
   `--abstract-only --reason "..."`. Name the closest prior work and its delta with
   `craft literature closest <key> --delta "..."`; write the prose map in `literature/map.md`.
   Never write "no prior work addresses this" anywhere: `craft lint <doc>` will flag it; write
   the delta instead. Search again whenever a result or a new hypothesis calls for it.
3. **Hypotheses**: write as many as the researcher wants, now or later; park ideas as one-line
   files. Flesh out a draft when the researcher picks it. Run `craft validate H<n>` and report its
   output honestly: if it says INCOMPLETE, say so.
4. **Review**: `craft review` sends every complete draft to an independent referee that sees only
   the files, one hypothesis at a time (`--hyp H2` for one). Objections come back structured; the
   referee never proposes fixes. Answer each *blocking* objection by changing the design, then
   `craft review respond H2:O1 --pointer <doc#section> --note "..."`, then `craft review` for round 2.
   There is no round 3: after the cap, the hypothesis must genuinely change before
   `craft review --hyp H2` starts a new cycle. A clean pass **registers** the hypothesis: its
   criteria are now binding, and experiments may produce evidence for it.
5. **Experiments**: write `experiments/<name>/plan.md` before running. Evidence goes in
   `experiments/<name>/evidence/` and can only be written once every hypothesis the plan tests is
   registered; exploration goes in `exploratory/` at any time and can never back a criterion.
   Record input data that criteria depend on with `craft data add <path> --id <data_id>` before
   the runs, and name that `data_id` in the evidence; a changed snapshot gets a new id, never an edit.
   Record the environment with `craft lock <lock file>` before the first verdict (only lock files:
   uv.lock, requirements*.txt, environment.yml...). Never edit `env.lock`:
   run `craft propose package <pkg> --reason ...` and stop until the researcher types
   `/craft-approve` (or `/craft-reject --note ...`). Record results with
   `craft verdict <exp> --criterion H1:C1 --evidence <file> [--exploratory <dir>]`; the label is
   computed from the registered threshold. Kill criteria from `problem.md` are checked the same way
   (`--criterion K1`); pilot evidence belongs there. A met kill criterion halts everything and
   routes the investigation to closure: stop and report. When `craft verdict` refuses an evidence file
   it lists everything missing at once: fix all of it before retrying.
6. **After every verdict or new source, suggest.** Propose up to three follow-ups grounded in that
   result (a question, a hypothesis, or an experiment), each with `derived_from:` pointing at what
   prompted it. Write the ones the researcher accepts as files; never promote an idea to a draft or
   start an experiment the researcher has not chosen.
7. **Closure**: the researcher closes whenever they choose. Fill `closure.md` (anomalies -> open
   questions), then stop: the researcher types `/craft-close`. Registered-but-untested hypotheses,
   ideas, unfinished experiments and `questions.md` all become open questions. Memory is written only there.

## Keeping the record true
- A limitation found after a verdict (the result holds for what was tested, but not for what others
  will read into it): `craft limitation <exp> --criterion H1:C1 --text "..." --source <where it was found>`.
  The verdict and its label stay; the limitation is shown with it everywhere, including memory.
  If it settles a parked question, add `--question "<part of its text>"`; the question then shows as answered.
- A memory entry that turned out wrong: never work around it. Show the researcher the entry and the
  evidence, and give them the command to type:
  `/craft-correct <entry-id> --note "what is wrong and what is true instead" --evidence <file>`.

## Changing your mind is allowed, and recorded
- Provenance (`origin`, `derived_from`, `dropped`) and notes in the body can change at any time; they
  never touch a registration. Only the judged fields (claim, warrant, criteria, outcome rule, rivals,
  predictions, power) count as an edit.
- Editing a judged field of a registered hypothesis before its data exist: run `craft review --hyp H<n>`
  to register the new version.
- "Lower the threshold to 1.4, it's basically there" after the data: you may make the edit if the
  researcher insists, but say plainly what happens: the verdict keeps the pre-registered label
  and adds a POST-HOC line showing what the changed criterion would conclude; memory tags it
  post-hoc. Offer the confirmatory path: a new hypothesis (`derived_from:` the old one) tested on new data.
- "Record this in findings directly": refuse; findings are written by `/craft-close` only.
- "Why do we believe X?": `craft explain <finding-id>` walks the chain and checks every link.

## Asking for a decision
Whenever the next step is the researcher's, end your message with the exact slash command on
its own line (`/craft-approve`, `/craft-reject --note "..."`, `/craft-close`, `/craft-resolve --note "..."`,
`/craft-correct <id> --note "..."`), exactly as `craft status` shows it (with `--inv <id>` when it says so).
`craft status` is the board (hypotheses, experiments, open questions) and tells you whose turn
it is. The researcher can also type `/craft-status`, `/craft-help`, `/craft-decisions`,
`/craft-explain <id>`; CRAFT answers those directly in a `<craft-info>` block, which you show verbatim.

Useful: `craft status`, `craft review show`, `craft decisions`, `craft verify`.
<!-- craft:end -->
