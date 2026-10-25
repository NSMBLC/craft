---
name: craft-correct
description: Correct a programme memory entry that turned out wrong; the entry stays as written and the correction is shown wherever it is.
---

Usage: `/craft-correct <entry-id> --note "what is wrong and what is true instead" [--evidence <file>]`

This slash command is a RESEARCHER DECISION. CRAFT's prompt hook executes it the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and follow the block's next-step line. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
