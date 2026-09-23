---
name: craft-status
description: Where each investigation stands, whose turn it is, and the exact next command.
---

Usage: `/craft-status`

This slash command is a RESEARCHER QUERY. CRAFT's prompt hook answers it directly and puts the answer in a `<craft-info>` block in this turn. Show that block's answer verbatim, make no tool calls, add nothing, and stop. If no block is present, say the hook did not run.
