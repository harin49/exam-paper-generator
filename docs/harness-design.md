# Harness design

The goal, the architecture and every decision taken for the exam-paper harness, with the reason for
each. Decisions are numbered (D1, D2, ...) and never renumbered; a changed decision is marked
superseded and points to the one that replaces it.

## Goal

> Given **any syllabus** (and optionally the textbook's chapter map) plus a **paper spec**, produce a
> question paper and answer key as PDFs that are correct, on-syllabus and balanced as the spec asks.
>
> **Every generated artifact is checked before a teacher sees it**: the questions, the answer key, the
> marking scheme and the rendered PDFs. Structure and arithmetic are checked by deterministic code.
> Correctness, clarity and syllabus fit are checked by reviewers independent of the writer.
>
> **Review findings go back to the writer, who revises the paper.** Every revision is checked again,
> by the scripts and by the reviewers, until it passes or a round limit is reached. Each finding ends
> up fixed, or rejected with a reason, and the teacher can see which.
>
> A teacher approves at defined points, and the process is repeatable, auditable and measurably good.

## Harness layers

A harness is everything around the model that makes its work reliable. These are the layers this
design has to cover.

| Layer | Question it answers |
|---|---|
| Orchestrator | Who decides what happens next? |
| State | What is done, and is it still valid? |
| Tools | What deterministic work exists (validators, blueprint, checker, renderer)? |
| Agents | Which model roles exist, and what can each see and do? |
| Guardrails | What is enforced, not just asked for? |
| Human in the loop | Where must a teacher decide? |
| Observability | What happened in a run? |
| Evals | Is quality getting better or worse across runs? |
| Domain packs | How does a new syllabus or subject plug in? |

## Decisions

### D1. Review findings are handled by severity

- **Error** (the key is wrong, or a question cannot be answered or has more than one correct answer):
  the writer fixes it without asking the teacher.
- **Warning** and **suggestion**: the teacher decides, per finding, whether the writer addresses it.

*Why:* nobody wants a wrong answer key shipped, so asking about errors wastes the teacher's attention;
warnings and suggestions are matters of judgement that belong to the teacher.

### D2. The reviewer sets severity; automatic fixes stay visible

The reviewer labels each finding's severity. Every fix made without asking is listed for the teacher
with the finding, the change and the result of the re-check, and the teacher can reverse it.

*Why:* a reviewer can label a matter of taste as an error; visibility keeps the teacher in control
without making them approve each error fix.

### D3. At most 3 write–review rounds

If a finding is still open after three rounds, it goes to the teacher as a disagreement, with the
writer's and the reviewer's positions side by side. The teacher settles it at gate 3 (D7) in one of
three ways:

- give the writer a specific instruction for one extra round;
- fix it themselves;
- reject the finding, with a reason.

*Why:* write–review loops can bounce forever when the writer and reviewer disagree; a cap hands the
dispute to a person.

### Review loop (D1–D3)

```mermaid
flowchart TD
    W[Writer drafts or revises the paper] --> S[Scripts check structure and arithmetic]
    S -->|fail| W
    S -->|pass| R[Blind solver and reviewer check the paper]
    R --> F{Open findings?}
    F -->|none| T[Teacher approves the paper]
    F -->|errors| N{Round 3 done?}
    F -->|warnings or suggestions| D[Teacher decides each one]
    D -->|address| N
    D -->|reject with a reason| T
    N -->|no| W
    N -->|yes| X[Teacher settles the disagreement at gate 3]
    X --> T
    T --> P[Render PDFs]
```

### D4. The host app is the harness; we configure it rather than write our own loop

Claude Code (or Cowork) runs the loop: it calls the model, runs tools, starts subagents and fires
hooks. This project supplies the parts it runs:

| Part | Role |
|---|---|
| Skill (`SKILL.md`) | The playbook: the steps and the rules |
| Scripts | Deterministic tools: validate, plan, check, compare, render |
| Agents | Independent roles: writer, blind solver, reviewer |
| Hooks | Enforcement: block actions that break the rules |

The user starts a paper by invoking the skill with a spec whose syllabus pack exists (a pack is made
once per syllabus with `/exam-papers:make-pack`); nothing else to set up.

*Why:* teachers should not need an API key or a Python orchestrator to run. Trade-off accepted: the
model still chooses to follow the playbook. Hooks can block a wrong action (the solver reading the key,
a write before approval) but cannot force the right next action. A Python orchestrator using the Claude
Agent SDK stays possible later for batch or headless runs.

### D5. Ship as one plugin for Claude Code and Cowork; claude.ai chat is not supported

The skill, scripts, agents and hooks are packaged as one plugin, installed from a Git marketplace (or a
zip upload in Cowork).

*Why:* both Claude Code and Cowork load skills, agents and hooks. claude.ai chat ignores agents and
hooks, so its "blind" solver would be the same conversation that wrote the key, which breaks the goal's
independent review.

Rule that follows: scripts live inside the skill folder, never in a top-level `bin/` (a `bin/` folder
makes Cowork refuse the whole plugin).

### D6. Approvals come only from a command the teacher types

The teacher approves by typing a command such as `/exam-papers:approve blueprint`. A `UserPromptExpansion`
hook (code that runs when a command the user typed expands, before Claude sees it) records the approval
in the task's `approvals.json`: which gate, which file, the file's SHA-256 hash and the time. It records
only when `command_name` is the plugin's approve command, `command_source` is `"plugin"` and there is
no `agent_id`. A `PreToolUse` hook blocks Claude from
writing `approvals.json`. A gate counts as passed only while the approved file still has the recorded
hash, so editing an approved file voids its approval.

```mermaid
sequenceDiagram
    actor T as Teacher
    participant H as UserPromptExpansion hook
    participant A as approvals.json
    participant C as Claude
    participant P as PreToolUse hook
    T->>H: /exam-papers:approve blueprint
    H->>A: gate, file, sha256, time
    C->>P: write approvals.json?
    P-->>C: blocked
    C->>A: read: blueprint approved and hash matches?
```

*Why:* trust comes from where an action originates. Only a command the teacher types expands, so
Claude and its subagents cannot create an approval; the hash ties the approval to the exact content
the teacher saw.

*Not `UserPromptSubmit`* (the first version of D6): it also fires for subagent hand-backs, messages
from other sessions and scheduled tasks, with nothing in its input saying which. The probe showed a
subagent's reply arriving through it as `<agent-message …>` text, so a hook that read approvals from
`UserPromptSubmit` could be fooled by a subagent that writes `/exam-papers:approve` in its reply.

*Limit:* this guards against mistakes, not a determined adversary. A `PreToolUse` hook can match
`Write`/`Edit` on the file exactly, but a Bash command can only be pattern-matched, so a creative
command could still slip through.

*As built (2026-10-28):*

- The command is `/exam-papers:approve GATE [FOLDER]` (`commands/approve.md`, with
  `disable-model-invocation: true` so Claude cannot run it as a skill). The hook is
  `hooks/approve.py`; the skill's `approvals.py` reads and writes the records.
- Without FOLDER, the hook records the approval in the one paper under `papers/` whose next step
  (`next_step.py`) is that gate. With none or several waiting, it blocks the command and says why.
- The gate's file holds no approval field (the blueprint's `status` is gone): `approvals.json` is the
  only record. `workflow.json` checks it with `{"approved": GATE}`; `make_blueprint.py` and
  `check_questions.py` read it too. The latest record for a gate is the one that counts.
- The guard denies `Write`, `Edit`, `MultiEdit` and `NotebookEdit` of any file named
  `approvals.json`, and every Bash command that mentions the name (reading uses the Read tool), so
  the probe's `2>&1` false alarm cannot happen.
- Each approval is also appended to `run.jsonl` as an `approved` event.

### D7. Four approval gates

Each gate is passed only by a typed command (D6).

| Gate | When | What the teacher approves |
|---|---|---|
| Concept list | Once per book, after `validate_concepts.py` passes (and once per paper in cloud Cowork, D18) | The concepts drafted from the syllabus |
| Blueprint | Every paper, before any wording is written | Chapter, concept, marks, kind and difficulty of every part |
| Finding decisions | After each review round with warnings or suggestions, and for any finding still open after round 3 | Accept or reject each warning and suggestion (errors are fixed without asking, D1); settle each disagreement (D3) |
| Final paper | After review ends, before the PDFs are rendered | The reviewed questions and key, and the list of automatic fixes (D2) |

The spec is not a gate: the teacher writes it, and `validate_paper_spec.py` checks it.

*Built:* all four. Gate 1 is `/exam-papers:approve concepts [PACK]`: the hook runs
`validate_concepts.py`, refuses a list with errors, and records the list's hash in
`syllabi/<pack>/approvals.json` (without PACK it picks the one pack whose list is not approved as it
is now); `make_blueprint.py` refuses an unapproved list, and the list's old `status` field is ignored
with a warning. Gate 2 is `/exam-papers:approve blueprint`, gate 3 `/exam-papers:decide` (D20) and
gate 4 `/exam-papers:approve paper` (the `approve_paper` step before rendering).

*Why:* each gate sits where a teacher's judgement is needed and a mistake would be costly to undo
later. The final gate was added by this design: before it, nothing asked the teacher to sign off
the finished paper.

### D8. First-version scope: science, maths and theory-only subjects

Beyond ICSE Class 9 Physics, the first version covers other science and maths subjects (numericals,
units, formulas, diagrams) and theory-only subjects (for example history, geography, languages). Maths
notation is handled by LaTeX (D10). Other boards and classes are not in the first version.

*Why:* science and maths are closest to what already works; theory-only subjects test whether the
design really generalises (no numericals, different question types, judgement-based marking).

### D9. A syllabus arrives as Markdown or plain text

The teacher supplies the syllabus as a Markdown or text file. PDF extraction is not in the first
version.

*Why:* it keeps text extraction and clean-up out of scope, so the work goes into drafting and checking
the concept list.

### D10. Maths notation is written in LaTeX

Question, answer and option text may contain LaTeX maths (for example `$\frac{a}{b}$`), which the
renderer turns into proper notation in the PDF. The HTML-style markup (`<sup>`, `<sub>`, `<b>`, `<i>`)
stays for simple cases.

*Why:* stacked fractions, roots and equations look wrong in HTML-style markup, and maths is in scope
(D8).

*As built (2026-11-03):*

- `$...$` is inline maths and `$$...$$` a centred equation on its own line, in every printed field;
  `\$` is a literal dollar sign. The shared `latex.py` splits text, checks formulas and draws them.
- Formulas are typeset by **matplotlib's mathtext**, not a TeX installation, so it works wherever
  the plugin runs (Cowork's sandbox has no TeX). It covers fractions, roots, powers and indices,
  Greek letters, integrals, sums and relations, but no environments (matrices, aligned equations).
- `render.py` draws each formula as a 600 dpi transparent image, sized to the text, dropped by its
  depth so it sits on the baseline; lines holding a tall formula grow (`autoLeading`). A displayed
  formula makes the text a list of flowables, which every table cell holding question text accepts.
  The images are drawn in a temporary folder and removed after the build.
- Rule **Q16** reports a formula that is unclosed or cannot be typeset, quoting it and the reason,
  at the check step rather than as a crash at the build. Rule **Q4** reads an MCQ option written
  `$4.5 \times 10^{3}$` as 4500.
- The blind solver gets the LaTeX source as written (`extract_paper.py` leaves it), which a language
  model reads directly.

### D11. Chapters are the syllabus's own units

A concept list is organised by the syllabus's units or sections, and a spec selects units. The book
becomes optional information.

*Why:* syllabi arrive without a book's contents (D9), so units are the only structure every syllabus
has. Consequence: the existing ICSE Physics list is organised by Selina book chapters (syllabus unit 4
"Fluids" is book chapters 4 and 5) and has to be moved to syllabus units.

*As built (2026-10-28):*

- The field names stay (`chapters` in concept lists and specs, `chapter` in blueprints and
  questions, `chapterWeightage` and so on); the formats define a "chapter" as a syllabus unit. This
  avoided a rename across about 270 references and every existing file. The PDFs and the review
  report print "Unit".
- Units are keyed by the syllabus's own numbers. Where a syllabus repeats numbers (History: Civics
  1-3, History 1-8) or has none, the teacher decides the numbering when the pack is made.
- Nothing checks a unit against the syllabus text (for example by point range); the teacher checks the
  grouping at gate 1.
- `book` is optional in concept lists and specs, and compared only when both name one.
- The ICSE Physics sample moved from 10 book chapters to the syllabus's 8 units (unit 4 Fluids = book
  chapters 4-5, unit 8 Electricity and Magnetism = 9-10); the example became
  `examples/icse9-physics-units1-4/` (book chapters 1-5 are units 1-4).

### D12. Syllabus packs and papers live in the teacher's workspace

The plugin holds only code, prompts and formats. Everything a teacher makes lives in their workspace
(the project folder in Claude Code, the attached folder in Cowork):

- `syllabi/<pack>/`: `syllabus.md`, `concepts.json`, approvals;
- `papers/<task>/`: spec, blueprint, questions, `review/`, `approvals.json`, PDFs.

*Why:* an installed plugin is a cache that should not be written to, and Cowork can only write to
attached folders. The teacher owns and can see everything.

*As built:* a spec names its pack in `exam.syllabusPack` (required, rule S20), and
`make_blueprint.py` reads `syllabi/<pack>/concepts.json` from the nearest folder above the spec, so a
paper never runs on a guessed concept list. A pack is made with `/exam-papers:make-pack` and approved
at gate 1 (D7); its syllabus points are numbered by a script (D21).

### D18. In cloud Cowork, one task makes one paper

Where hooks run in a sandbox that ends with the task (Cowork on Pro and Max plans, and on Team and
Enterprise when cloud sessions are on), a paper is made from start to finish in one task. Approvals,
`state.json` and `run.jsonl` are trusted only inside that task. At the end, the whole paper folder (PDFs,
spec, blueprint, questions, review, `approvals.json`, `state.json`, `run.jsonl`) is delivered to the
teacher's folder as a record. A new task starts a new paper. Syllabus packs are read from the teacher's
folder and checked again with `validate_concepts.py` in every task.

Where hooks run beside the teacher's folder (Claude Code on their computer, local Cowork), D12 applies
as written and a paper can span several sessions.

*Why:* Anthropic's Cowork architecture article says cloud sessions run in a sandbox that is "destroyed
when it ends", and that Cowork runs in the cloud on Pro and Max plans. The probe showed hooks writing
inside that sandbox. A file Claude copies out and back in is a Claude action, which D6 does not trust,
so trust cannot carry from one cloud task to the next. Which plans teachers will use is not known yet,
so the design has to work in the cloud case.

Each cloud task also re-approves the concept list: before the blueprint, it shows the list's summary
and hash and asks for a typed `/exam-papers:approve concepts`. The record delivered from an earlier task is
shown for reference only.

*Why re-approve:* the earlier record is a copy Claude wrote into the teacher's folder; a changed list
together with a changed record would pass a hash check. One typed command per paper keeps D6's rule
that only typed commands create trust.

### D13. A writer subagent drafts and revises the questions

Main Claude only orchestrates: it runs the steps, talks with the teacher and passes work between roles.
A writer subagent drafts `questions.json` from the approved blueprint and revises it for accepted
findings.

*Why:* clear roles and smaller contexts, and each role's tools and file access can be set separately
(the writer never needs the solver's answers; the solver never sees the key).

### D20. How the review loop runs (settles D1–D3 and D13 in detail)

- **The reviewer judges every solver mismatch.** Each `[V…]` line becomes a finding with a severity,
  or goes in the report's `dismissed` list with a reason. The loop then deals only in `R` findings,
  and the writer never needs the solver's output.
- **Rounds 2 and 3:** the reviewer gets its previous findings, the writer's responses and what
  changed. It marks each previous finding `resolved` or `open` and reviews only the changed parts
  for new problems. Finding IDs stay the same across rounds, so "still open after round 3" is exact.
- **The writer runs `check_questions.py` itself** and fixes structural errors before handing back;
  script failures never count as a review round. The workflow's check step only confirms it.
- **The writer answers each finding** in `review/writer-response.json`: `fixed` with the change, or
  `disagree` with its evidence. Its "disagree" is the writer's side of a dispute (D3).
- **Gate 3 is a typed command,** `/exam-papers:decide accept R2 R4 reject R5`, recorded by a hook
  against the hash of that round's reviewer report and refused while any open warning, suggestion
  or dispute is left undecided. Reasons and instructions for the writer are given in chat.
- **Disputes after round 3** are settled with the same command: `accept` gives the writer one more
  round with the teacher's instruction; `reject` leaves the paper as it is. To fix it themselves,
  the teacher edits `questions.json`, then rejects the finding.
- **Automatic fixes stay visible (D2):** every change the writer makes without asking is listed at
  gate 4; the teacher can undo any of them with `/exam-papers:decide reject ID` (piece 4). (The
  first plan had the teacher ask in chat; a typed command keeps D6's rule.)
- **Rounds are counted from `review/rounds.json`**, which `review_status.py --close-round` appends to
  after each review (it also saves the round's questions and report in `review/rounds/N/`). This
  replaced "count from `run.jsonl`": a repeated `--done` could double-count there.
- **Guards:** a `PreToolUse` hook (`hooks/guard_agents.py`) uses `agent_type` to keep the blind
  solver to the blind paper (`solver-input.json` in, `solver-answers.json` out) and the writer away
  from the solver's answers and the comparison; the writer may read the blueprint but not change it.

*Why:* bounded rounds with stable finding IDs make the cap in D3 checkable; typed decisions keep
D6's rule that only the teacher's own commands create trust; the writer learning only from findings
keeps the solver's mistakes out of the key.

*Built in four pieces:* (1) the writer agent, the guards and mismatch triage (done 2026-10-28);
(2) the reviewer every round, `review_status.py` and the loop in `workflow.json` (done 2026-10-28);
(3) the typed `/exam-papers:decide`, writing `review/decisions.json` (done 2026-10-28); (4) the
gate-4 list of automatic fixes (done 2026-10-28).

*As built in piece 2:*

- `review_status.py TASK` says what is next: `close` (a review not yet closed as a round),
  `decide` (gate 3), `revise` (the writer, without asking) or `done`. The workflow steps
  `close_round`, `decide_fixes` and `apply_fixes` are done when it says they are not needed, so the
  loop comes from conditions; no step jumps back.
- **A round is identified by the report, `questions.json` and `writer-response.json` together.** A
  report can repeat word for word (no findings twice, or a writer who changed nothing); keyed on the
  report alone, such a round never closed and the paper could reach gate 4 with an error open.
- **A decision is tied to its round number,** not the report's hash: a dispute accepted in round 3
  gives exactly one more round, even if round 4's report repeats round 3's.
- `fixes.json` became `review/decisions.json`: one entry per decision, `{round, report, accepted,
  rejected}`. Claude wrote it until piece 3, when the decide hook took over in the same format
  (piece 4 added the `undo` list).
- The reviewer may change a finding's severity, with a `note`; after an automatic round the teacher
  sees the status summary and the writer's responses, and the loop goes on without waiting; a
  teacher's edit after the loop is a new round, and at the cap anything flagged in it is a dispute.
- `next_step.py` gained `flags` and `reads` for `passes` conditions, and a `recorded` input that was
  missing when recorded counts as unchanged while it is still missing.

*As built in piece 3:*

- `/exam-papers:decide accept R2 R4 reject R5 [FOLDER]` (`commands/decide.md`, not runnable by
  Claude) is recorded by the same hook as approvals (`hooks/approve.py`), through
  `review_status.record_decision`. It goes to the one paper waiting at `decide_fixes` or
  `apply_fixes`, or the named folder.
- One command decides every finding listed under "Teacher to decide" and "Disputes"; the hook blocks
  it, naming the missing IDs, until all are covered. Only listed findings can be accepted; listed
  findings and open errors can be rejected, so the teacher can overrule the reviewer on an error even
  while the writer is due to fix it.
- The guard that protects `approvals.json` now protects `decisions.json` the same way.

*Changed after the live run (2026-11-03):* finding R4 ("part (a) is tagged medium but is plain
recall") used rounds 2 and 3 with no change: the writer said the blueprint fixes tags, the reviewer
kept it open. Three changes:

- `make_blueprint.py` puts each question's easier parts first (marks and kind move with the
  difficulty, so no balance changes). Before, every Section B question came out (a) medium,
  (b) easy, because difficulty went to the biggest parts first and ties by position.
- The writer treats a difficulty or kind tag as a target its wording must meet, and fixes a "does
  not fit its tag" finding by changing the question; the reviewer words its suggested fix that way.
- A finding the writer disagreed with, which the reviewer keeps open in the next round, is a dispute
  at once (gate 3), not only after round 3: the writer has given its reason, and another automatic
  round would repeat it.

*As built in piece 4:*

- Closing a round also saves the writer's response that led to it (`review/rounds/N/
  writer-response.json`); before, each revision overwrote the last, so by gate 4 only the final
  explanation was left.
- `review_status.py TASK --fixes` lists, round by round, every writer response labelled AUTOMATIC,
  ACCEPTED BY YOU or UNDONE BY YOU, the reviewer's verdict on it in the next round, and the text
  before and after (from the round snapshots); then every change no writer response accounts for
  (a hand edit, or anything made after the last review). Gate 4 shows it verbatim, so nothing
  changes silently.
- **Undo** is `/exam-papers:decide reject ID` on a resolved finding the writer fixed, typed at gate 4
  (or earlier). The hook records it in the decision's `undo` list; `review_status.py` then says
  `revise` with the ID under "Writer to revert"; the writer restores the before-text and answers
  `reverted`; a new round reviews the result, and the finding stays closed. Rejecting a dispute is
  not an undo: only a *resolved* fixed finding is reverted.

### D21. Syllabus points get unique ids from a script

- `number_syllabus.py` copies the teacher's syllabus into the pack, inserting `[S1]`, `[S2]`, ...
  before each paragraph and list item (headings excluded). Nothing else changes.
- A concept's `source` is a point id; `validate_concepts.py` checks that every point has a concept or
  is listed in the concept list's `notTested` with a reason (a heading line, a note, a limit such as
  "Simple numerical problems").
- This replaced section ids that copied the syllabus's own numbering (`[4(ii)]`), which Claude had to
  add by judgement: real syllabi reuse numbers (History numbered Civics 1-3 and History 1-8) and use
  (a)-(d), so the ids had to be invented and the syllabus rewritten, which could drop or change text.
  Quoting the syllabus instead was considered and dropped: deciding what counts as a "point" for
  quotes needed tuning (clauses gave 160 points for Physics, most of them limits and repeats), and it
  meant reworking the validator.

*Why:* a script adds the ids, so no judgement and no risk to the text; coverage is checked per
paragraph (Physics: 53 points, 6 not tested), finer than the old sections (22). The ids carry no
meaning, so gate 1 shows each one beside its text.

### D14. State is a hash ledger plus a run log

- `state.json` in each task folder records every finished step with the SHA-256 hashes of its inputs
  and outputs. Claude records a step with `next_step.py TASK --done STEP_ID` when it finishes.
- A step that is checked by its inputs (`"recorded"` in `workflow.json`) is done while its inputs still
  have the recorded hashes and its outputs exist. Changing an input makes that step and every step
  after it due again. Steps whose files prove them (a check that passes, an approval in
  `approvals.json`) keep those conditions.
- Output hashes are recorded for the audit trail but are not checked. The teacher may edit
  `questions.json` by hand after `apply_fixes`; checking outputs would send the paper back to
  applying the same fixes again. (The first version also had to allow for the approval setting
  `status` in `blueprint.json`; approvals now live only in `approvals.json`, D6.) Any edit is still
  caught, because each step's outputs are a later step's inputs.
- `--done` refuses a step while an earlier step is not done, while one of its outputs is missing, or
  while its own done condition would still fail. Conditions that read the step's own outputs are
  ignored for the "earlier step" test: `apply_fixes` edits `questions.json`, which makes the check
  and the blind solver due again, as it should.
- `run.jsonl` is an append-only record with times, one JSON object per line. Its events are `done`
  (every recorded step, by `--done` or by a script that records itself), `approved` (D6), `decided`
  (D20) and `round_closed` (D20). Agent calls and script results are not logged yet; the run
  metrics in D17 will need them.
- Task folders made before this have no `state.json` and start again (no migration).
- *Changed after the live run (2026-11-03):* Claude once wrote the blueprint and forgot `--done`, and
  the blueprint approval was then refused with "no paper is waiting", which pointed the teacher the
  wrong way. So the four script steps (`make_blueprint`, `extract_paper`, `compare_solutions`,
  `render`, marked `"recordsItself"` in `workflow.json`) now record themselves when they succeed,
  through the same `record_done`; `render` does not while a diagram image is missing. Subagent and
  user steps still use `--done` (Claude recorded every one in the live run). When a gate command
  finds no paper waiting, the hook now lists each paper's next step and, if that step's output is
  already there, says it is unrecorded and gives the `--done` command. Recording on "the output
  exists" alone was rejected: a file can be left from an older input.

*Why:* file timestamps break on a copy, a `git checkout` or any re-save (re-printing the review findings
once sent a finished paper back to an earlier step). Hashes depend only on content. The log gives the
teacher an audit trail (D2) and gives the evals their data (D17). JSON lines, so scripts can count
rounds and failures without parsing text.

### D15. Each syllabus pack declares its own kinds

The concept list declares the subject's kinds (Physics: `numerical`, `theory`; History, for example:
`recall`, `explanation`, `source_analysis`), and the spec balances on those. Difficulty (easy, medium,
hard) stays common to all subjects.

*Why:* it matches each subject's real exam pattern, and the scripts stay generic: they read the list of
kinds instead of knowing about numericals.

### D16. No new question formats in the first version

The formats stay MCQ, and short and long answers with parts. Theory subjects use these: a source or
passage can go in a question's `stem`, with parts that refer to it.

*Why:* keeps the first version's work on the harness itself. Source-based questions, essays with
rubrics, and fill-in or match items can be added later.

### D17. Evals: planted errors, run metrics and golden papers

- **Planted errors:** inject known mistakes into a known-good paper (wrong key, unanswerable question,
  off-syllabus part, marking that does not add up) and measure how many the solver and reviewer catch.
- **Run metrics:** from `run.jsonl`: check failures, solver mismatches, findings by severity, rounds
  used, automatic fixes, and findings the teacher rejected.
- **Golden papers:** a fixed set of syllabi and specs rerun after every change to the prompts or
  scripts, with their metrics compared to the previous run.

*Why:* unit tests check the scripts, not the agents. Planted errors show whether review works; run
metrics and golden papers show whether a change made things better or worse.

### D19. Plugin name, repo layout, sample pack and dev loading

- **Name:** `exam-papers`. It is permanent and prefixes everything: the skills are
  `/exam-papers:make-paper` and `/exam-papers:make-pack` (a short skill that makes a syllabus pack
  with make-paper's scripts; no workflow file, since a pack is made once), the agents are
  `exam-papers:writer`, `exam-papers:blind-solver` and `exam-papers:reviewer`, and the commands are
  `/exam-papers:approve` and `/exam-papers:decide`.
- **Layout:** the repo is a marketplace (`.claude-plugin/marketplace.json`) listing one plugin,
  `plugins/exam-papers/`. Tests, docs and examples stay in the repo and are not installed.
- **Paths:** the skill names its own files as `${CLAUDE_SKILL_DIR}/…` and runs every command from the
  teacher's workspace. Agents get every path they need in their prompt (the docs do not say that
  `${CLAUDE_SKILL_DIR}` works inside agent files).
- **Sample pack:** the ICSE Class 9 Physics (Selina) pack ships read-only in the skill, under
  `assets/syllabi/`. The skill copies it into the workspace's `syllabi/` only when the teacher agrees
  (D12: packs a paper uses live in the workspace).
- **Development:** the plugin is installed from this repo's own marketplace, so names and loading
  match what teachers get. A plugin installed from a local folder is read in place, so edits take
  effect after `/reload-plugins`.

*Why:* a permanent name that is specific but short to type at every gate; only the plugin ships; one
sample pack lets a teacher try a paper without writing a concept list first.

### Architecture

```mermaid
flowchart LR
    subgraph Plugin["Plugin (installed, read-only)"]
        SK[Skill: playbook, scripts, formats]
        AG[Agents: writer, blind solver, reviewer]
        CM[Commands: /exam-papers:approve, /exam-papers:decide]
        HK[Hooks: record approvals and decisions, block leaks]
    end
    subgraph WS["Teacher's workspace"]
        SY["syllabi/&lt;pack&gt;/"]
        PA["papers/&lt;task&gt;/"]
    end
    Plugin --> WS
```

```mermaid
flowchart TD
    S[Syllabus .md] --> CL[Draft concept list] --> V1[validate_concepts.py] --> G1{{Gate 1: concept list}}
    G1 --> SP[Teacher's spec] --> V2[validate_paper_spec.py] --> BP[make_blueprint.py] --> G2{{Gate 2: blueprint}}
    G2 --> WR[Writer subagent drafts] --> CK[check_questions.py]
    CK -->|fail| WR
    CK -->|pass| RV[Blind solver + reviewer]
    RV -->|errors, rounds left| WR
    RV -->|warnings, suggestions| G3{{Gate 3: finding decisions}}
    G3 -->|address, rounds left| WR
    RV -->|still open after round 3| G3
    G3 -->|dispute: instruction for one extra round| WR
    G3 -->|dispute: teacher fixes or rejects| G4
    RV -->|nothing open| G4{{Gate 4: final paper}}
    G3 -->|all rejected| G4
    G4 --> R[render.py: PDFs]
```

### Facts behind D4 and D5 (checked 2026-10-28)

From Anthropic's [plugin platform-support page](https://claude.com/docs/plugins/platform-support.md):

| Plugin part | claude.ai chat | Cowork | Claude Code |
|---|---|---|---|
| Skills | Loads | Loads | Loads |
| Commands | Loads as a skill | Loads (`/plugin:cmd`) | Loads |
| Agents | Ignored | Loads | Loads |
| Hooks (`hooks/hooks.json`) | Ignored | Loads | Loads |
| Top-level `bin/` | Plugin refused | Plugin refused | Loads |

### Probe results (2026-10-28)

A throwaway plugin (`probe`) tested what the docs leave open. It ran in a Cowork task, which ran in a
cloud workspace (`/home/claude`, Linux, Python 3.13) linked to the desktop app, not on the user's Mac.
The raw `probe-hook.log` confirms every result below. The Claude Code baseline has not run.

| Test | Result |
|---|---|
| Plugin hooks fire | Yes: `PreToolUse`, `UserPromptSubmit`, `UserPromptExpansion`, `SubagentStart`, `SubagentStop` |
| A hook can block a subagent's file read | Yes. Hook input inside a subagent has `agent_id` and `agent_type` (`probe:solver`), so the solver's calls can be told apart |
| A plugin agent's `tools` list is enforced | Yes: Grep, Edit and Bash were "not available" to an agent limited to Read and Write |
| A hook can block Claude's writes to a file | Yes, for Write and for a Bash `echo … >` |
| A typed plugin command triggers | `UserPromptExpansion` with `command_name: "probe:approve"`, `command_source: "plugin"` (recorded the approval) |
| A subagent's reply `/probe:approve …` triggers | `UserPromptSubmit` only, as `<agent-message …>` text; no `UserPromptExpansion`, so no forged approval |
| `reportlab` and `matplotlib` | Already installed (5.0.1, 3.11.2); pip works |
| Plugin agent names | Prefixed with the plugin name: `probe:solver` |

Also seen:

- `UserPromptSubmit` text is not what the user typed: the app puts `<system-reminder>` text in front
  of it, so even the user's own `/probe:approve` did not start with the command.
- The Bash guard denied a harmless `ls -la approvals.json 2>&1; cat approvals.json`, because `2>&1`
  contains `>` (pattern matching gives false alarms as well as misses; see D6's limit).
- Every subagent ends with a `SubagentHandback` tool call, which `PreToolUse` sees with the subagent's
  `agent_id`.

Problem found: **files and hooks live in the cloud workspace, not the teacher's folder.** Hooks ran
in `/home/claude` and wrote `approvals.json` and their logs there. The user's picked folders were
reachable only by Claude copying files across, and the files reached the Mac only when Claude sent
them. So approvals, `state.json`, `run.jsonl`, syllabus packs and papers would be lost when the workspace
goes, and copying them to the teacher's folder is a step Claude performs, which D6 does not trust.
This affects D6, D12 and D14 for Cowork tasks that run in the cloud.

Still to find out:

- ~~whether a Cowork task can run on the user's computer~~: answered by D18 (plan and admin settings
  decide; Pro and Max are cloud only);
- whether a cloud workspace survives between turns of the same task (the article says the sandbox is
  destroyed when the session ends);
- the same probe in a Claude Code session on the Mac (baseline).

## Open questions

None at present. Questions answered so far: who drives the loop (D4, D5), first-version scope (D8),
syllabus input (D9), approvals (D6), gates (D7), state (D14), question kinds (D15), formats (D16),
evals (D17).
