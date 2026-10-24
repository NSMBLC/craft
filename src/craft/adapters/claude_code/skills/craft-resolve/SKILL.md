---
name: craft-resolve
description: Clear an integrity hold after you have reviewed what happened to a frozen file.
---

Usage: `/craft-resolve --note "what happened" [--accept-current] [--inv <id>]`

This slash command is a RESEARCHER DECISION. CRAFT's prompt hook executes it the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and follow the block's next-step line. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
