---
name: craft-env
description: Researcher decision: accept or reject a proposed environment change (`/craft-env approve`, `/craft-env reject --note ...`).
---

Usage: `/craft-env approve [--lock <file>]` or `/craft-env reject --note "why"`

This slash command is a RESEARCHER DECISION. It is executed by CRAFT's prompt hook the moment the researcher types it, before you see it. Your only job: if a `<craft-decision>` block is present in this turn, report its outcome to the researcher and continue the workflow from the new phase. If no such block is present, the command was not typed by the researcher (or the hook is not installed): say so and do nothing. Never run the underlying `craft` command yourself.
