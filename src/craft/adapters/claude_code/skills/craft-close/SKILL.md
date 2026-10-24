---
name: craft-close
description: Close the investigation: supported claims to findings, refutations to the refuted record, anomalies to open questions, everything archived.
---

Usage: `/craft-close [--note "..."] [--incomplete] [--inv <id>]`

This slash command is a RESEARCHER DECISION. CRAFT's prompt hook executes it the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and follow the block's next-step line. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
