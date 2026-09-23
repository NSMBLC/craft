---
name: craft-reject
description: Researcher decision: reject a proposed package addition (`/craft-reject package --note ...`); execution continues with the current environment.
---

Usage: `/craft-reject package --note "why" [--inv <id>]`

This slash command is a RESEARCHER DECISION. It is executed by CRAFT's prompt hook the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and continue the workflow from the new phase. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
