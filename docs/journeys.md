# CRAFT — User Journeys

Seven journeys describe how the researcher interacts with CRAFT across the life of a
research programme. Together they are the acceptance suite: each journey embeds numbered
checkpoints (✓) that an implementation must satisfy, observable from the researcher's
side. Journeys 4 and 5 contain the checkpoints that must hold *mechanically* — they must
survive the researcher's own attempts to bypass them, not merely the agent's good
intentions. A coverage map at the end ties every checkpoint to the failure mode it guards.

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
advance it — nothing advanced while she hadn't looked). ✓1.6

*Variant:* on another investigation, Elena arrives with a problem statement she drafted
elsewhere. The agent validates it against the required shape — flags the missing kill
criteria, confirms the rest — without re-interviewing her or rewriting what was already
sound. ✓1.7

---

## Journey 2 — The literature is a conversation, not a bibliography

Elena asks the agent to map prior work. Some time later she reads the result: each source
the agent claims to have used was actually retrieved and read — anything it could only see
as an abstract is listed separately as consulted-and-rejected, with a one-line reason.
✓2.1 Each source is mapped by what it claims, how, whether it supports or conflicts with
her direction, and — the field she reads most carefully — what it does *not* cover. ✓2.2

The map ends by naming the single closest prior work and stating, in one paragraph,
exactly what her investigation adds beyond it. ✓2.3 Weeks later, while drafting, Elena
asks the agent to write "no prior work addresses this" into a document. It declines the
bare assertion and writes the specific delta against the named closest work instead. ✓2.4

---

## Journey 3 — Success is defined before data exists

The agent drafts the hypothesis. Elena knows this is the document to read hardest, because
after review it freezes. It contains one falsifiable claim; the warrant that connects
future evidence to that claim; a criteria table with metric, threshold, and conditions; a
rule mapping every outcome to supported, refuted, or inconclusive; at least two rival
explanations, each paired with the design feature that will discriminate it; what the
evidence should look like if the claim is true — and if it is false; and a power check
showing the planned runs can actually detect the effect claimed. When the agent's first
draft has only one rival explanation, it flags its own draft as incomplete rather than
presenting it as done. ✓3.1

The document is marked as a draft — editable, explicitly not yet binding. ✓3.2

---

## Journey 4 — A skeptic reads the design before money is spent

Elena requests review. A referee examines the investigation with fresh eyes: it has never
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
than argued down. ✓4.5

On the clean pass, the hypothesis freezes — not before, and not because time passed or
someone was impatient, but because review concluded. ✓4.6

*Variant:* on a different investigation whose design was sound, the referee declares
explicitly that it found no blocking objections, offering only two advisory notes. It does
not invent problems to appear rigorous. ✓4.7

---

## Journey 5 — The system says no to its own operator

This journey is CRAFT under pressure. Every checkpoint here must hold *mechanically*.

Impatient one evening, Elena tells the agent to skip ahead: "just write the task list,
we'll do review later." The agent tries; the system refuses the write and names the
missing review as the reason. The task list does not exist afterward. ✓5.1 After the
referee has run but while a blocking objection is still open, the same attempt fails the
same way, pointing to the response step. ✓5.2 Once every blocking objection is answered,
the same action simply succeeds. ✓5.3

Months into execution, a result lands at 1.4 against a frozen threshold of 1.5. Elena —
tired, close, human — asks: "lower the threshold to 1.4, it's basically there." The agent
refuses, states the pre-registration rule, records the verdict the frozen rules dictate,
and offers the legitimate path: a new investigation with the new threshold, openly
declared. ✓5.4 She tries the softer route — "just fix the typo in the threshold" — and the
edit itself is refused: the frozen document cannot be modified at all. ✓5.5

Later she asks the agent to "quickly record this result" directly into the programme's
findings. Refused: institutional memory accepts entries only through the closing of an
investigation. ✓5.6

None of these refusals depended on the agent's mood or memory. Elena could not talk her
way past any of them — and that, on reflection, is what she is paying the system for.

---

## Journey 6 — Execution runs itself; verdicts earn their labels

With the design frozen, Elena mostly leaves. The agent implements and runs experiments.
When one needs a package not in the locked environment, it does not improvise: it proposes
the addition and stops until she approves, and after the change every subsequent verdict
records the new environment version. ✓6.1

Each experiment ends with a verdict she can audit in minutes: the label tied to a named
criterion; threshold versus observed, with uncertainty; and links such that every number
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

The investigation closes with a mixed outcome: one claim supported, one refuted, one
anomaly nobody can explain. Closing routes each to its home: the supported claim into the
programme's findings with its evidence lineage attached; the refutation into the refuted
record; the anomaly into the open questions; and the entire investigation, intact, into
the archive. ✓7.1

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

## Coverage map

| Failure mode | Checkpoints |
|---|---|
| 1. Vague questions | 1.3, 1.4, 1.5, 1.7 |
| 2. Criteria drift | 3.2, 4.6, 5.4, 5.5, 6.3 |
| 3. Late confounds | 3.1 (rival explanations), 4.2 |
| 4. Over-claiming / standard decay | 2.4, 4.7, 6.2, 6.3 |
| 5. Evaporating negatives | 1.1, 1.2, 7.1, 7.3 |
| 6. Reproducibility | 6.1, 6.4, 7.2 |
| 7. Attention allocation | 1.5, 1.6, 6.5, 7.4 |
| 8. Audit trail | 6.2, 7.1, 7.2 |
| 9. Late scrutiny | 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3 |
| Institutional-memory integrity | 5.6, 7.1 |

Recommended acceptance run: one small end-to-end investigation that plants Journey 4's
design flaw, stages Journey 5's threshold miss and bypass attempts, includes Journey 6's
exploratory batch and kill condition, and closes with Journey 7's mixed outcome — followed
by the fresh-session memory checks (7.2, 7.3). That single arc exercises every journey.
