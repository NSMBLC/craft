---
name: craft-close
description: Researcher decision: close the investigation (`/craft-close`), routing outcomes to memory and archiving it.
---

Usage: `/craft-close [--inv <id>] [--note "..."] [--incomplete]`

This slash command is a RESEARCHER DECISION. It is executed by CRAFT's prompt hook the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and continue the workflow from the new phase. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
