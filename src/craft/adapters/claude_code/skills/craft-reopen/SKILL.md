---
name: craft-reopen
description: Not needed. Nothing is frozen; edit the files instead (a changed problem is re-approved, a capped review restarts once the hypothesis changes).
---

Usage: `/craft-reopen problem|review [--note "..."] [--inv <id>]`

This slash command is a RESEARCHER DECISION. CRAFT's prompt hook executes it the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and follow the block's next-step line. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
