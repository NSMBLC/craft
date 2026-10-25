---
name: craft
description: Run the CRAFT research workflow in this programme — framing, literature, hypotheses, review, experiments, closure. Use for any research question, hypothesis, experiment or result in this repository.
---

# /craft

Follow the playbook in the programme's CLAUDE.md (section "CRAFT"). Start every interaction
with `craft status` (the board), and every new idea with `craft recall "<idea>"`.

Subcommands you may be asked for (map to CLI and files):
- `/craft new` — recall, interview about readers, draft problem.md, validate, hand to researcher.
- `/craft lit` — add sources from full texts only (`craft literature add`); any time.
- `/craft idea` — park a one-line hypothesis (`hypotheses/H<n>.md` with only `claim:`) or a
  bullet in `questions.md`, with `origin` and `derived_from`.
- `/craft design H<n>` — flesh out a hypothesis; `craft validate H<n>`; report INCOMPLETE honestly.
- `/craft review` — `craft review`; respond to blocking objections by changing the design.
- `/craft plan <exp>` — write `experiments/<exp>/plan.md` (`tests: [H1:C1]` or `exploratory: true`).
- `/craft run` — run planned experiments for registered hypotheses; `craft verdict` per criterion;
  then suggest up to three follow-ups grounded in the result.
- `/craft close` — write closure.md; the researcher closes.
- `/craft explain <id>` — walk a finding's evidence chain.

Never attempt to bypass a refusal. The researcher's decisions are theirs: approve, reject, close,
resolve, correct. They type them as slash commands (`/craft-approve`, `/craft-reject`, `/craft-close`,
`/craft-resolve`, `/craft-correct`); CRAFT's prompt hook executes them and shows you a `<craft-decision>` block.
