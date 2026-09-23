---
name: craft-explain
description: Walk a finding's evidence chain: claim, criterion, observed result, files, with every link checked.
---

Usage: `/craft-explain <entry-id>` (e.g. F-0001, R-0002)

This slash command is a RESEARCHER QUERY. CRAFT's prompt hook answers it directly and puts the answer in a `<craft-info>` block in this turn. Show that block's answer verbatim, make no tool calls, add nothing, and stop. If no block is present, say the hook did not run.
