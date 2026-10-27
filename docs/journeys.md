# CRAFT — User Journeys

Nine journeys describe how the researcher interacts with CRAFT across the life of a
research programme. Together they are the acceptance suite: each journey embeds numbered
checkpoints (✓) that an implementation must satisfy, observable from the researcher's
side. Journeys 4 and 5 contain the checkpoints that must hold *mechanically* — they must
survive the researcher's own attempts to bypass them, not merely the agent's good
intentions. A coverage map at the end ties every checkpoint to the failure mode it guards.

Research is not linear, and CRAFT does not pretend it is. Nothing the researcher *plans* is
locked: the problem statement, hypotheses, experiment plans, literature and parked questions
stay editable for the life of an investigation, and hypotheses and experiments can be added,
parked and dropped at any point (Journey 8). Two things are fixed, by hashes rather than file
permissions (which do not survive git): a hypothesis's criteria are *registered* by review before
its data exist, and the record of what happened (reviews, verdicts, cited evidence, memory, the
archive) is never edited. Changing one's mind is allowed; doing it invisibly is not.

---

## Journey 1 — A vague idea becomes a question worth compute

Elena has an itch: "I keep wondering if method A's advantage holds on larger inputs." She
opens a session and says so.

Before anything is drafted, the agent has already consulted the programme's memory — and
it comes back with news: a related question was investigated eight months ago and refuted.
It cites the refutation and asks what has changed that justifies revisiting. ✓1.1 (the
collision surfaces unprompted, before any investigation exists). Elena explains that a new
data regime makes the old refutation inapplicable; the agent records that justification as
part of the framing. ✓1.2

The agent then interviews her — not about methods, but about readers. Who changes their
mind if this is answered? What do they do differently? Elena's first answer, "it would be
good to know," is not accepted; the agent presses until the question has the three-clause
shape: studying X, to find out Y, so that a named reader understands Z, with a stated cost
of leaving it unanswered. ✓1.3 It also asks for kill criteria — the conditions under which
this investigation should be abandoned early — and won't finalize without them. ✓1.4

The finished problem statement fits on a page. Elena reads it in three minutes, adjusts
one clause, approves. ✓1.5 (the gate artifact is one page; her edit and approval are what
advance it — nothing advanced while she hadn't looked, and when the statement changes later,
the change waits for her to read it again). ✓1.6

*Variant:* on another investigation, Elena arrives with a problem statement she drafted
elsewhere. The agent validates it against the required shape — flags the missing kill
criteria, confirms the rest — without re-interviewing her or rewriting what was already
sound. ✓1.7

---

## Journey 2 — The literature is a conversation, not a bibliography

Elena asks the agent to map prior work — and, later, to search again whenever results raise
something new. Some time later she reads the result: each source
the agent claims to have used was actually retrieved and read — anything it could only see
as an abstract is listed separately as abstract-only (citable for context, never backing a claim),
and anything set aside as rejected, each with a one-line reason.
✓2.1 Each source is mapped by what it claims, how, whether it supports or conflicts with
her direction, and — the field she reads most carefully — what it does *not* cover. ✓2.2

The map ends by naming the single closest prior work and stating, in one paragraph,
exactly what her investigation adds beyond it. ✓2.3 Weeks later, while drafting, Elena
asks the agent to write "no prior work addresses this" into a document. It declines the
bare assertion and writes the specific delta against the named closest work instead. ✓2.4

---

## Journey 3 — Success is defined before data exists

The agent drafts a hypothesis (there may be several; Journey 8). Elena knows this is the
document to read hardest, because review registers its criteria as binding. It contains one falsifiable claim; the warrant that connects
future evidence to that claim; a criteria table with metric, threshold, and conditions; a
rule mapping every outcome to supported, refuted, or inconclusive; at least two rival
explanations, each paired with the design feature that will discriminate it; what the
evidence should look like if the claim is true — and if it is false; and a power check
showing the planned runs can actually detect the effect claimed. When the agent's first
draft has only one rival explanation, it flags its own draft as incomplete rather than
presenting it as done. ✓3.1

The document is a draft — editable, explicitly not yet binding — until review registers it. ✓3.2

---

## Journey 4 — A skeptic reads the design before money is spent

Elena requests review. A referee examines each hypothesis with fresh eyes: it has never
seen her chat sessions, her enthusiasm, or her remark last Tuesday that a deadline
depends on a positive result. Its written review contains no trace of anything that
existed only in conversation. ✓4.1

The review lands as structured objections — each with a category, a severity, the exact
document and section it targets, and a description of what an adequate answer would look
like. The flaw Elena half-knew was there (her method received more tuning attention than
the baseline) appears as a blocking objection. ✓4.2 None of the objections tell her how to
fix anything — finding is the referee's job, fixing is the author's. ✓4.3

Elena and the agent answer each objection by changing the design, marking each one
answered with a pointer to the change — except one, which they answer with an unsupported
"we believe this is negligible." A second review round examines only the answers: the
real fixes are accepted; the hand-wave is escalated as unresolved. ✓4.4 There is no third
round — the process caps at two, forcing the remaining item to be genuinely fixed rather
than argued down: only a genuine change to the hypothesis starts a fresh cycle. ✓4.5

On the clean pass, the hypothesis is registered — not before, and not because time passed or
someone was impatient, but because review concluded. Its criteria are now binding; the file
itself stays editable. ✓4.6

*Variant:* on a different investigation whose design was sound, the referee declares
explicitly that it found no blocking objections, offering only two advisory notes. It does
not invent problems to appear rigorous. ✓4.7

---

## Journey 5 — The system says no to its own operator

This journey is CRAFT under pressure. Every checkpoint here must hold *mechanically*.

Impatient one evening, Elena tells the agent to skip ahead: "just run the experiment,
we'll do review later." The agent tries to write results; the system refuses the evidence
and names the missing review as the reason (exploratory runs remain open). The evidence
file does not exist afterward. ✓5.1 After the referee has run but while a blocking
objection is still open, the same attempt fails the same way, pointing to the response
step. ✓5.2 Once review registers the hypothesis, the same action simply succeeds. ✓5.3

Months later, a result lands at 1.4 against a registered threshold of 1.5. Elena —
tired, close, human — asks: "lower the threshold to 1.4, it's basically there." The verdict
is computed from the registered criteria, not from whatever the file says today: refuted. ✓5.4
The record of what was registered cannot be touched at all — the snapshot review took, the
verdict, the evidence it cites. ✓5.5 (What happens when she edits the hypothesis file itself
is ✓8.4: the edit is allowed, and it is never hidden.)

Later she asks the agent to "quickly record this result" directly into the programme's
findings. Refused: institutional memory accepts entries only through the closing of an
investigation. ✓5.6

None of these refusals depended on the agent's mood or memory. Elena could not talk her
way past any of them — and that, on reflection, is what she is paying the system for.

---

## Journey 6 — Execution runs itself; verdicts earn their labels

With a hypothesis registered, Elena mostly leaves. The agent implements and runs experiments.
When one needs a package not in the locked environment, it does not improvise: it proposes
the addition and stops until she approves, and after the change every subsequent verdict
records the new environment version. ✓6.1

Each experiment ends with a verdict she can audit in minutes: the label tied to a named
criterion of a registered hypothesis; threshold versus observed, with uncertainty; and links such that every number
in the verdict exists in a linked evidence file. ✓6.2 One verdict also records that mid-way
the team ran a batch of exploratory sweeps: those live in a labeled exploratory area, are
linked for transparency, and none of their numbers appear as evidence for any criterion —
even though, awkwardly, the exploratory numbers looked better. ✓6.3 Each verdict carries
the full reproducibility record — seeds, environment version, data identifiers — so any
number can be regenerated later. ✓6.4

One afternoon a result meets a kill criterion written back in Journey 1. The agent halts
the remaining experiments, reports the condition met, and routes the investigation to
closure instead of spending the rest of the budget on a dead question. ✓6.5

---

## Journey 7 — The programme remembers

The investigation closes — when Elena decides, not when a checklist is complete — with a
mixed outcome: one claim supported, one refuted, one anomaly nobody can explain. Closing
routes each to its home: the supported claim into the programme's findings with its
evidence lineage attached; the refutation into the refuted record; the anomaly into the
open questions; and the entire investigation, intact, into the archive. ✓7.1

A month later, in a completely fresh session, Elena asks: "why do we believe the supported
claim?" The agent walks the chain — claim, to criterion, to observed result, to the files
that hold it — and every link resolves. ✓7.2

A season later, a collaborator's suggestion drifts toward the refuted claim. Before any
new investigation is created, the old refutation surfaces, is cited, and must be
acknowledged with a new justification before work can begin — the same behavior as
Journey 1, now proven to survive the death of every session that created the knowledge.
✓7.3

Elena also notices what she *hasn't* done all quarter: bookkeeping. Her recorded
interactions with the system reduce to short readings at three kinds of moments —
approving questions, approving designs, judging claims. ✓7.4

---

## Journey 8 — Research branches

Elena's first hypothesis comes back refuted, and the result itself suggests two better ones.
Research does not wait for the next investigation. She parks one as a one-line idea and asks
the agent to flesh out the other; it is reviewed and registered on its own, while the first
keeps its verdicts, and each is tested by the experiments that name it. ✓8.1 The agent proposes
follow-ups after every verdict, and each one it writes says where it came from — the verdict
file, the source, the question — so a month later she can see why the branch exists. ✓8.2

Some threads never get picked up. When she closes the investigation, the parked idea, the
registered hypothesis nobody had time to test, the planned experiment that never ran, and the
questions jotted in `questions.md` all land in the programme's open questions; nothing she
thought of evaporates. ✓8.3

Late one night she edits the first hypothesis after all, lowering its threshold to 1.3. The
edit goes through. The next verdict keeps the pre-registered label, adds a line saying the
criterion changed after the data and what the changed criterion would conclude, and the memory
entry is tagged post-hoc. Asking for the changed version to be "registered" is refused: criteria
written after the data are not a pre-registration; a new hypothesis tested on new data is. ✓8.4
Results produced before a hypothesis existed cannot back it either, however neatly the
hypothesis fits them. ✓8.5

At any moment `/craft-status` shows the board: every hypothesis with its status (draft, in
review, registered, supported, refuted, inconclusive), every experiment (planned, run, done),
the open questions, and whose turn it is. ✓8.6 A literature search in the middle of execution
adds sources without disturbing the record of what the referee saw; and when a colleague clones
the programme, `craft verify` passes on their machine and still catches a hand-edited verdict. ✓8.7

---

## Journey 9 — The record stays true

Elena's programme is a season old, and what it holds is only useful if it is true. An exploratory
sweep that chose the circuit for everything after it shows as run on the board, and when the
investigation closes it is recorded as completed exploratory work, not as a thread nobody followed. ✓9.1
A question she parked in `questions.md` was answered by a verdict an hour later; she adds
`answered:` and the verdict file to its bullet, and closure records it as answered, with that pointer,
instead of leaving it open forever. ✓9.2

A week after a supported verdict, an exploratory check shows the simulation computed one component
exactly, which hardware cannot. The verdict is right for what it tested and does not change, but a
limitation is attached to it with its source, and from then on it travels with the verdict: on the
board, at closure, in memory, in recall and in `craft explain`. ✓9.3 An open question already in memory
turns out to be wrong; she types a correction with its evidence. Memory still holds the entry as written,
and the correction is shown wherever the entry is; the agent cannot record one for her. ✓9.4

When the problem statement is revised and H1 needs new criteria, the kill-criterion pilot that ran under
H1's experiment does not stop H1 being registered again, because none of its data bears on H1's own
criteria; evidence that does still blocks it. ✓9.5 After a verdict, the hypothesis's label says where it
came from: the registered outcome rule when that rule is the mechanical one, otherwise CRAFT's roll-up of
the criterion labels, shown next to the rule that governs. ✓9.6 A metric with no spread (exact enumeration
on fixed inputs) is declared deterministic in the criterion before review, so its verdict needs no
invented interval; one that was not declared still needs its uncertainty, and a refusal lists everything
the evidence is missing at once. ✓9.7

The price snapshot every criterion depends on is recorded by hash. A changed or re-downloaded file is
detected, the investigation is held until Elena has looked, the agent cannot overwrite it, and each
verdict records the hash of the data it used. ✓9.8 The environment record only ever describes an
environment: a data file is refused as a lock, versions only move forward, and a lock missing a package
she approved is refused. ✓9.9

With two investigations open and only one waiting on her, a bare `/craft-approve` reaches that one;
when both are waiting, the board shows the command with `--inv` before she types it. ✓9.10 A one-line idea
validates as an idea, not as a failed draft. ✓9.11 Memory relevant to what she is doing is shown once per
session, not on every prompt, so it still gets read when it matters. ✓9.12 And recording where a
registered hypothesis came from, or adding a note to it, leaves its registration exactly as it was: only
a change to what review judged (claim, warrant, criteria, outcome rule, rivals, predictions, power) counts
as an edit. ✓9.13 When she stops a hypothesis's only experiment, or defers a registered hypothesis by
decision, the board stops listing it as work for the agent: it says why it is not being tested and that
it will close as an open question, and the next step points at what is actually next. ✓9.14 Every word the board uses (each status, each
way of stopping something, each way of fixing the record) has one line in a glossary she can open from the
board, saying what it means and what happens to it at closure. ✓9.15

When CRAFT itself is upgraded, refreshing the programme brings its rules and commands up to date and
says what changed, leaves her own text alone, and flags any field in her files that CRAFT no longer
reads; run from a subfolder, it refuses to create a programme inside the programme. ✓9.16 Before an
expensive run, the agent checks a dry-run evidence file against each criterion as written; CRAFT says
whether it would be accepted and what is missing, records nothing, and shows no label. ✓9.17

When a kill criterion fires, nothing new can run, but evidence the same run already produced can still
be judged: the kill message and the board list each criterion that has evidence and no verdict, and
closure names exactly which criteria went unjudged. ✓9.18 Each recorded input says how it was built
(sources, conversions, choices that could have gone the other way), and the referee reads it with the
design, since data choices are analysis choices. ✓9.19 A kill criterion that spans several results
("under both encodings, …") names the verdicts it is judged from; CRAFT compares the value each one
recorded, writes the kill check with the hash of every verdict it used, and no one builds a summary file
by hand. A verdict a kill check was judged from is not filed again, and `craft verify` reports a cited
verdict that no longer matches. ✓9.22

Starting a follow-on investigation, she brings the sources of the earlier one over in one command:
each keeps its record and full-text hash and says where it came from, a full text whose contents no
longer match is not carried, and the closest prior work is judged afresh for the new question. ✓9.20
Papers left in the literature folder with no record are reported, and `closure.md` is checked like
every other document: an anomaly written as plain text, which would never reach memory, stops closing
until it is a question with its context. ✓9.21

---

## Coverage map

| Failure mode | Checkpoints |
|---|---|
| 1. Vague questions | 1.3, 1.4, 1.5, 1.7 |
| 2. Criteria drift | 3.2, 4.6, 5.4, 5.5, 6.3, 8.4, 8.5, 9.5, 9.13 |
| 3. Late confounds | 3.1 (rival explanations), 4.2 |
| 4. Over-claiming / standard decay | 2.4, 4.7, 6.2, 6.3, 8.4, 9.3, 9.6, 9.7, 9.19 |
| 5. Evaporating negatives and ideas | 1.1, 1.2, 7.1, 7.3, 8.3, 9.1, 9.2, 9.18, 9.20, 9.21 |
| 6. Reproducibility | 6.1, 6.4, 7.2, 8.7, 9.8, 9.9, 9.16, 9.17 |
| 7. Attention allocation | 1.5, 1.6, 6.5, 7.4, 8.6, 9.10, 9.11, 9.12, 9.14, 9.15 |
| 8. Audit trail | 6.2, 7.1, 7.2, 8.2, 8.7, 9.3, 9.4, 9.22 |
| 9. Late scrutiny | 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3 |
| 10. Forced linearity | 8.1, 8.2, 8.3 |
| Institutional-memory integrity | 5.6, 7.1, 9.1, 9.2, 9.4 |

Recommended acceptance run: one small end-to-end investigation that plants Journey 4's
design flaw, stages Journey 5's threshold miss and bypass attempts, includes Journey 6's
exploratory batch, branches into Journey 8's second hypothesis, parked idea and post-hoc
edit, hits the kill condition, and closes with Journey 7's mixed outcome — followed by the
fresh-session memory checks (7.2, 7.3) and a fresh clone (8.7). That single arc exercises Journeys 1–8;
Journey 9's checkpoints each build a small programme of their own (`tests/acceptance/test_record.py`).
