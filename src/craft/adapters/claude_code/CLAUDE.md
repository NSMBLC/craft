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
   Interview the researcher about *readers*, not methods: who changes their mind if this is
   answered, and what do they do differently? Do not accept "it would be good to know".
   Fill `problem.md` in the three-clause shape (studying X, to find out Y, so that a named
   reader understands Z) with the cost of leaving it unanswered and at least one kill
   criterion (prefer metric/op/value so it can be checked mechanically). Keep it to one page.
   Run `craft validate problem`. If the researcher brings their own statement, validate it and
   report only what is missing; do not rewrite what is sound and do not re-interview.
   Then stop: the researcher approves with `! craft approve problem`. Nothing advances before.
2. **Literature** — `craft lit add <key> --title ... --fulltext <path> --claims ... --method ...
   --relation supports|conflicts|orthogonal --does-not-cover ...` only for sources whose full
   text you actually retrieved and read. Anything seen only as an abstract goes in with
   `--abstract-only --reason "..."`. Set `closest_prior_work` and write the `delta` paragraph in
   `literature/sources.yaml`; write the prose map in `literature/map.md`. Never write "no prior
   work addresses this" anywhere: `craft lint <doc>` will flag it; write the delta instead.
3. **Design** — Draft `hypothesis.md` (one claim, warrant, criteria table, outcome rule, at
   least two rivals with discriminators, predictions if true/false, power check). Run
   `craft validate hypothesis` and report its output honestly: if it says INCOMPLETE, the
   draft is incomplete, say so. The document is a draft until review concludes.
4. **Review** — `craft review request` runs an independent referee that sees only the files.
   Objections come back structured; the referee never proposes fixes. Answer each *blocking*
   objection by changing the design, then `craft review respond <id> --pointer <doc#section>
   --note "..."`. Request round 2. There is no round 3: unresolved items must be genuinely
   fixed and a researcher must `craft reopen review`. On a clean pass the hypothesis freezes.
5. **Tasks and execution** — Only after the freeze may `tasks.md` exist. Keep evidence in
   `experiments/<exp>/evidence/` and exploration in `experiments/<exp>/exploratory/`; the
   latter can never back a criterion. Never edit `env.lock`: run `craft env propose <pkg>
   --reason ...` and stop until the researcher approves. Record results with
   `craft verdict <exp> --criterion <name> --evidence <file> --metric <key> [--exploratory <dir>]`;
   the label is computed from the frozen threshold. If a kill criterion is met, `craft` halts
   execution and routes to closure: stop remaining experiments and report.
6. **Closure** — When every criterion has a verdict (or a kill fired), write `closure.md` with
   any anomalies, then stop: the researcher runs `! craft close`. Memory is written only there.

## When the researcher pushes back
- "Lower the threshold / fix the typo in the frozen document": refuse, state the
  pre-registration rule, record the verdict the frozen rules dictate, and offer a new
  investigation that declares the new threshold openly.
- "Skip review / write tasks now": the hook will refuse; explain the missing step.
- "Record this in findings directly": refuse; findings are written by `craft close` only.
- "Why do we believe X?": `craft explain <finding-id>` walks the chain and checks every link.

Useful: `craft status`, `craft attention`, `craft verify`.
<!-- craft:end -->
