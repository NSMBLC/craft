---
claim: ""                # exactly one falsifiable sentence (an idea can be just this line)
origin: researcher       # researcher | agent
derived_from: ""         # what prompted it: a verdict, experiment, source (lit:<key>) or question
warrant: ""              # why the planned evidence bears on the claim
criteria:
  - name: C1
    metric: ""
    op: ">="
    threshold: 0
    conditions: ""       # seeds, input sizes, budgets under which the metric counts
outcome_rule:
  supported: ""
  refuted: ""
  inconclusive: ""
rivals:                  # at least two, each with the design feature that discriminates it
  - explanation: ""
    discriminator: ""
  - explanation: ""
    discriminator: ""
predictions:
  if_true: ""
  if_false: ""
power:
  effect_size: 0
  n_runs: 0
  method: ""
  detectable: ""         # statement of why the planned runs can detect the effect
---

# Hypothesis {hid} — {id}

A draft until `craft review` registers it. The file stays editable after that: a change to the
criteria or outcome rule after registration is recorded as post-hoc in every verdict and memory entry.
