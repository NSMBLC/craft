# Changelog

CRAFT follows [semantic versioning](https://semver.org). While it is at 0.x, a minor version adds or
changes behaviour (a command, flag or field, a new refusal or warning, a change to what CRAFT writes) and a
patch only fixes behaviour back to what was intended. Breaking changes are marked **Breaking**. After
upgrading, run `craft init` at the root of each programme; it reports the version it refreshed from.

## Unreleased

- A criterion can declare what it is judged on (`judged_on: interval | point | upper_bound | lower_bound`) and,
  when the evidence supplies its own interval, how that interval is computed (`interval_method`, which the
  evidence must match); the verdict says which, and validation flags criteria that cannot be judged as
  written (#4). Kill criteria take `judged_on` too (point estimate by default, as before); for kills judged
  from verdicts it replaces `of:`, which still works.
- `judged_on: interval` on a registered criterion states the default and does not change the registration.
- A file pointer in `derived_from` (`hypotheses/H1.md#criteria`) is read as that file, not as a hypothesis of
  another investigation; only one naming no file is flagged, and `craft renumber` rewrites it (#36).

## 0.1.0 — 2026-10-26

First tagged release: the non-linear registry (several hypotheses and experiments, statuses derived, record
don't lock) with the fixes from UAT rounds 1 and 2.

- `craft --version`; `craft init` records the version in `craft.yaml` as `craft_version` and reports
  "from X to Y" when it refreshes a programme.
- Hypotheses have a programme-wide identity, `<inv>/H<n>`, accepted wherever one is referenced;
  `craft renumber` renames an unreviewed hypothesis (#10).
- Generated inputs are recorded by generator, seeds and environment (`craft data add --generated --seeds`),
  fetched inputs by the run that fetched them (`--fetched`) (#8).
- A kill criterion can be judged from recorded verdicts (`from:`, `of:`, `combine:`), with each cited
  verdict's hash checked by `craft verify` (#12).
- The shell screen judges each line of a command on its own and traces inline Python writes through
  function arguments (#2).
- `craft validate closure`, stray-file warnings for literature, and a refused close when anomalies would be
  lost (#14).
- `craft literature carry` brings sources and hash-checked full texts over from another investigation (#13).
- Pre-kill evidence can still be judged, unjudged evidence is shown, and data derivations reach the
  referee (#19, #20, #21).
