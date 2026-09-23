---
name: craft
description: Run the CRAFT research workflow in this programme — framing, literature, design, review, execution, closure. Use for any research question, hypothesis, experiment or result in this repository.
---

# /craft

Follow the phase playbook in the programme's CLAUDE.md (section "CRAFT"). Start every
interaction with `craft status`, and every new idea with `craft recall "<idea>"`.

Subcommands you may be asked for (map to CLI):
- `/craft new` — recall, interview about readers, draft problem.md, validate, hand to researcher.
- `/craft lit` — build literature/sources.yaml + map.md from full texts only.
- `/craft design` — draft hypothesis.md; validate; report INCOMPLETE honestly.
- `/craft review` — `craft review request`; respond to blocking objections by changing the design.
- `/craft run` — write tasks.md (only once frozen), execute, `craft verdict` per criterion.
- `/craft close` — write closure.md; the researcher closes.
- `/craft explain <id>` — walk a finding's evidence chain.

Never attempt to bypass a refusal. The researcher's decisions are theirs: approve, close, reopen,
untaint, env approve. They type them as slash commands (`/craft-approve problem`, `/craft-close`, `/craft-env approve`,
`/craft-reopen review`, `/craft-untaint`); CRAFT's prompt hook executes them and shows you a `<craft-decision>` block.
