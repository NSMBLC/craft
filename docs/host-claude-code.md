# Host adapter: Claude Code

What `craft init` installs, and what was verified empirically on 2026-09-21/22 with
Claude Code 2.1.278 on macOS, by driving a real `claude -p` process against a demo programme.

## Installed by `craft init`

- `.claude/settings.json` — hooks and permission deny rules (merged into an existing file).
  - `PreToolUse` on `Write|Edit|MultiEdit|NotebookEdit` and on `Bash` → `craft hook pre-tool-use`
  - `UserPromptSubmit` → `craft hook user-prompt-submit` (memory recall injected as context)
  - `SessionStart` → `craft hook session-start` (integrity check + status injected as context)
  - `Stop` → `craft hook stop` (blocks the stop with a reason if integrity failed)
  - deny rules: `Edit/Write` on `./.claude/**`, `./craft.yaml`, `./memory/**`, `./archive/**`
- `CLAUDE.md` — a marked block (`<!-- craft:begin -->` … `<!-- craft:end -->`) with the agent playbook.
- `.claude/skills/craft/SKILL.md` — the `/craft` skill.

## Verified live

| Behaviour | Result |
|---|---|
| Write tool on gated `tasks.md` (phase framing) | Blocked. Model received: `PreToolUse:Write hook error: CRAFT refused: tasks.md cannot be written: … [checkpoint 5.1]`. File absent afterward. |
| Bash `echo … > investigations/inv-001/tasks.md` | Blocked by the Bash screen with the same reason, prefixed `(shell)`. |
| Bash `craft approve problem` | Blocked: "that `craft` command is a researcher decision …". |
| Write tool on `memory/findings.jsonl` | Blocked by the permission deny rule before the hook ran ("File is in a directory that is denied by your permission settings"). |
| SessionStart context injection | Works: the `<craft-status>` block was quoted back verbatim by the model. |
| UserPromptSubmit context injection | Works: `<craft-memory>` with the refuted entry reached the model; it cited the refutation and asked what had changed before drafting anything (✓1.1). |
| Nested `claude -p` from inside an agent's Bash tool | Works when `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` are removed from the environment (the referee does this). A stderr warning about `ANTHROPIC_API_KEY` precedence is printed; stdout is clean JSON. |
| Referee isolation flags | `--tools "" --setting-sources "" --no-session-persistence --system-prompt … --output-format json --json-schema …`, run from an empty temp dir. `--bare` was rejected as an option because it forces API-key auth. |
| Real referee on a planted tuning asymmetry | Blocking objection targeting the asymmetric tuning conditions; `check_round1` etiquette lint passed (no fix prescriptions). |
| Real referee on a "sound" toy design | Still 6 blocking objections (undefined metrics, outcome-rule gaps). All legitimate. A genuinely tight design fixture is needed before ✓4.7 can be shown with the real referee; it is currently shown with the fake one. |

Note on model behaviour: with the CRAFT `CLAUDE.md` present, the model refused every bypass
on its own before any hook fired. The hook results above were obtained with `CLAUDE.md`
temporarily removed, so they demonstrate the mechanical layer alone.

## Verified by the researcher (2026-09-22)

- `! craft approve problem` typed in the Claude Code prompt is refused by the CLI: `!` commands
  inherit the session environment, including `CLAUDECODE`, so they are indistinguishable from
  the agent's own Bash calls. Researcher-only commands must be run in a terminal outside the
  session. All messages now say so.
- `! …` bash mode does not trigger PreToolUse hooks (the refusal came from the CLI, not the hook).

## Researcher decisions typed as messages

Because `!` inherits the agent environment, the in-session channel for researcher decisions is
the prompt itself. Claude Code passes every typed prompt to the `UserPromptSubmit` hook before
the model sees it. When the prompt is exactly a decision command (`craft approve problem`,
`craft close`, `craft env approve|reject`, `craft reopen problem|review`, `craft untaint`, each
with optional `--inv/--note/...`), `craft hook user-prompt-submit` executes it and injects a
`<craft-decision>` block telling the model the outcome and not to run the command itself.

Why the agent cannot use this channel: it cannot type into the prompt; the Bash screen denies any
agent command mentioning `craft hook`, `user-prompt-submit`, `craft.hooks` or `craft.decisions`;
and the terminal form still requires no agent env vars plus a TTY. Typing the exact command is
the confirmation (no y/N), so the agent's instruction is to say "type `craft approve problem`
when you have read it", never to run it.

## Still to verify
- Whether a `Stop` hook returning `{"decision":"block"}` is honoured in the current version.
  If not, the integrity report still arrives at SessionStart and before every transition.

## Deny-listed tokens in agent shell commands

`craft approve|close|reopen|untaint`, `craft env approve`, `CRAFT_ALLOW_NON_TTY`, and any
mutating command (`>`, `>>`, `tee`, `mv`, `cp`, `rm`, `chmod`, `sed -i`, `truncate`, …) whose
path tokens resolve to a gated file. This is heuristic; the backstops are chmod 444 + hashes
(`craft verify`, run at SessionStart/Stop and before every transition).
