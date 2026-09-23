<!-- craft:begin -->
# CRAFT — how research is done in this programme

This repository is a CRAFT research programme. You (the agent) operate the `craft` CLI; the
researcher only decides. The rules below are *also* enforced by hooks: when a write is refused,
relay the refusal reason verbatim, state the rule, and offer the legitimate path. Never try to
route around a refusal (no shell redirects, no chmod, no editing state.json or settings).

## The workflow, phase by phase

1. **Framing** — Before drafting anything, run `craft recall "<the researcher's words>"`. If it
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
2. **Literature** — `craft literature add <key> --title ... --fulltext <path> --claims ... --method ...
   --relation supports|conflicts|orthogonal --does-not-cover ...` only for sources whose full
   text you actually retrieved and read. Anything seen only as an abstract goes in with
   `--abstract-only --reason "..."`. Set `closest_prior_work` and write the `delta` paragraph in
   `literature/sources.yaml`; write the prose map in `literature/map.md`. Never write "no prior
   work addresses this" anywhere: `craft lint <doc>` will flag it; write the delta instead.
3. **Design** — Draft `hypothesis.md` (one claim, warrant, criteria table, outcome rule, at
   least two rivals with discriminators, predictions if true/false, power check). Run
   `craft validate hypothesis` and report its output honestly: if it says INCOMPLETE, the
   draft is incomplete, say so. The document is a draft until review concludes.
4. **Review** — `craft review` runs an independent referee that sees only the files.
   Objections come back structured; the referee never proposes fixes. Answer each *blocking*
   objection by changing the design, then `craft review respond <id> --pointer <doc#section>
   --note "..."`. Run `craft review` again for round 2. There is no round 3: unresolved items must be genuinely
   fixed and the researcher types `/craft-reopen review`. On a clean pass the hypothesis freezes.
5. **Tasks and execution** — Only after the freeze may `tasks.md` exist. Keep evidence in
   `experiments/<exp>/evidence/` and exploration in `experiments/<exp>/exploratory/`; the
   latter can never back a criterion. Record the environment with `craft lock <file>` before
   execution. Never edit `env.lock`: run `craft propose package <pkg> --reason ...` and stop until
   the researcher types `/craft-approve` (or `/craft-reject --note ...`). Record results with
   `craft verdict <exp> --criterion <name> --evidence <file> --metric <key> [--exploratory <dir>]`;
   the label is computed from the frozen threshold. When the last criterion gets its verdict, or a
   kill criterion is met, `craft` routes the investigation to closure itself: stop remaining
   experiments and report.
6. **Closure** — Fill `closure.md` (anomalies -> open questions), then stop: the researcher
   types `/craft-close`. Memory is written only there.

## Asking for a decision
Whenever the next step is the researcher's, end your message with the exact slash command on
its own line (`/craft-approve`, `/craft-reject --note "..."`, `/craft-close`, `/craft-reopen review`,
`/craft-resolve --note "..."`). `craft status` tells you whose turn it is. The researcher can
also type `/craft-status`, `/craft-help`, `/craft-decisions`, `/craft-explain <id>`; CRAFT answers
those directly in a `<craft-info>` block, which you show verbatim.

## When the researcher pushes back
- "Lower the threshold / fix the typo in the frozen document": refuse, state the
  pre-registration rule, record the verdict the frozen rules dictate, and offer a new
  investigation that declares the new threshold openly.
- "Skip review / write tasks now": the hook will refuse; explain the missing step.
- "Record this in findings directly": refuse; findings are written by `craft close` only.
- "Why do we believe X?": `craft explain <finding-id>` walks the chain and checks every link.

Useful: `craft status`, `craft decisions`, `craft verify`.
<!-- craft:end -->
