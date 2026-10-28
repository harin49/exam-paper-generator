---
name: make-paper
description: Make an exam question paper and a teacher answer key (two PDFs) from a paper spec JSON. Use when the user supplies a paper spec (spec.json) or asks for an exam paper, question paper or answer key for a syllabus that has an approved concept list.
---

# Make an exam paper

Produces a question paper and a teacher answer key as PDFs. The paper is defined by a **paper spec**
the user provides. Scripts decide the structure and check the result; you write only the wording.

## Ground rules

- **Code decides structure, you write wording.** Chapters, marks, kinds, difficulty and concepts for
  every question come from `blueprint.json`. Never change a slot. Arithmetic is checked by script.
- **Run exactly the scripts named in this file, with the exact paths given.** Do not write your own
  version of what a script does, and do not run a script that is not listed for the step. Check the
  exit code of every script; stop on one this file does not expect.
- **Never assume.** If something in the spec or a script's output is unclear, ask the user.
- **One step at a time, in order.** Before every step, run `python3 "${CLAUDE_SKILL_DIR}/scripts/next_step.py" TASK`
  and do only the step it prints (see "Order of work"). Never run two steps side by side: do not start
  a step, read ahead for it or prepare it while a script or subagent from an earlier step is still
  running. Wait for each subagent to finish before doing anything else. When a step has finished,
  record it with the `--done` command `next_step.py` prints, report the step briefly, then run
  `next_step.py` again. Stop and wait at the approval points (spec errors, blueprint, decisions on
  findings, final paper).
- **Approvals and decisions come only from the user typing them.** The blueprint and the final paper
  are approved when the user types `/exam-papers:approve blueprint` or `/exam-papers:approve paper`,
  and review findings are decided with `/exam-papers:decide accept ... reject ...`; a hook records
  them in `TASK/approvals.json` and `TASK/review/decisions.json`. Ask the user to type the command.
  Never write, edit or copy either file (a hook blocks it), and never treat "approved" or a decision
  in chat as recorded.
- **The writer subagent writes the questions; you orchestrate.** Never write or edit
  `questions.json` yourself, even for a small fix: start the writer in revise mode.
- **Show script and reviewer output verbatim** when it contains errors or findings. Do not summarise
  them away, and do not change anything because of them until the user has seen them.
- **Refer to scripts by file name** (`check_questions.py`), not "the checker".
- **Never edit an approved concept list.** If a concept is wrong or missing, tell the user; changes
  go through a reviewed diff.

## Paths

There are two places:

- **This skill's folder**, `${CLAUDE_SKILL_DIR}`: the scripts, the formats, `workflow.json` and a
  sample syllabus pack. Read from it; never write into it.
- **The teacher's workspace**: the folder you work in. Run every command from it. It holds
  `syllabi/<pack>/` (a syllabus and its approved concept list) and `papers/<task>/` (one folder per
  paper). Paths in this file without `${CLAUDE_SKILL_DIR}` are relative to the workspace.

`TASK` means the paper's task folder, `papers/<board>-<class>-<subject>-<date>/` (for example
`papers/icse-9-physics-2026-10-27/`). Step 0 creates it and prints its path. `spec.json`,
`blueprint.json`, `questions.json`, diagram images, `review/` and the two PDFs all live in `TASK`.

`PACK` means the paper's syllabus pack, `syllabi/<pack>/` (for example
`syllabi/icse9-physics-selina/`), holding `syllabus.md` and `concepts.json`.

### Scripts used in the workflow

| Step | Script (exact path) | What it does | Writes |
|---|---|---|---|
| every | `${CLAUDE_SKILL_DIR}/scripts/next_step.py` | Prints the one step that may run next (order from `${CLAUDE_SKILL_DIR}/workflow.json`) | nothing |
| 0 | `${CLAUDE_SKILL_DIR}/scripts/new_paper.py` | Makes `TASK` and copies the user's spec into it | `TASK/spec.json` |
| 1 | `${CLAUDE_SKILL_DIR}/scripts/validate_paper_spec.py` | Checks the spec (rules S1-S19) | nothing |
| 2 | `${CLAUDE_SKILL_DIR}/scripts/make_blueprint.py` | Plans every question slot from the spec and concept list | `TASK/blueprint.json` |
| 4 | `${CLAUDE_SKILL_DIR}/scripts/check_questions.py` | Checks the questions (rules Q1-Q15) | nothing |
| 5.1 | `${CLAUDE_SKILL_DIR}/scripts/extract_paper.py` | Makes the paper with no answers for the blind solver | `TASK/review/solver-input.json` |
| 5.3 | `${CLAUDE_SKILL_DIR}/scripts/compare_solutions.py` | Compares the solver's answers with the key (rules V1-V6) | `TASK/review/compare-output.txt` |
| 5.4 | `${CLAUDE_SKILL_DIR}/scripts/render_review.py` | Checks the reviewer's findings and makes the HTML report (run by the reviewer; `--print` shows the findings again and writes nothing) | `TASK/review/reviewer-report.html` |
| 5.5-5.7 | `${CLAUDE_SKILL_DIR}/scripts/review_status.py` | Closes each review round and says what happens next (`--changes`: what changed since the last round) | `TASK/review/rounds.json`, `TASK/review/rounds/N/` |
| 6 | `${CLAUDE_SKILL_DIR}/scripts/render.py` | Builds the question paper and answer key PDFs | two PDFs in `TASK` |

Files that are **not** run in the workflow: `${CLAUDE_SKILL_DIR}/scripts/spec_types.py`,
`${CLAUDE_SKILL_DIR}/scripts/approvals.py` and `${CLAUDE_SKILL_DIR}/scripts/task_files.py` (libraries
the other scripts and the plugin's approval hook import) and
`${CLAUDE_SKILL_DIR}/scripts/number_syllabus.py` (used by the make-pack skill) and
`${CLAUDE_SKILL_DIR}/scripts/validate_concepts.py` (only when the user asks
you to check a concept list).

### Other files used

| What | Exact path |
|---|---|
| Spec format and template | `${CLAUDE_SKILL_DIR}/schemas/paper-spec-format.md`, `${CLAUDE_SKILL_DIR}/schemas/paper-spec.template.json` |
| Question format (the writer reads it; you need it to explain a finding) | `${CLAUDE_SKILL_DIR}/schemas/question-format.md` |
| Review file formats | `${CLAUDE_SKILL_DIR}/schemas/review-format.md` |
| Concept list format | `${CLAUDE_SKILL_DIR}/schemas/concept-list-format.md` |
| Sample pack: ICSE Class 9 Physics (Selina) | `${CLAUDE_SKILL_DIR}/assets/syllabi/icse9-physics-selina/` |
| Writer, blind solver and reviewer | the plugin's agents `exam-papers:writer`, `exam-papers:blind-solver` and `exam-papers:reviewer` |

## Order of work

The steps, their order and the approval points are listed in `${CLAUDE_SKILL_DIR}/workflow.json`.
`next_step.py` reads it, looks at what is in `TASK`, and prints the one step that may run next:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/next_step.py" TASK
```

- Run it before every step (from step 1 on; before step 0 there is no `TASK`). Do the step it prints,
  and nothing else, until that step has finished.
- When the step has finished, record it with the command it printed:
  `python3 "${CLAUDE_SKILL_DIR}/scripts/next_step.py" TASK --done STEP_ID`. This saves the hashes of
  the step's files in `TASK/state.json` and appends to `TASK/run.jsonl`. A step that is not recorded
  is not done, and `next_step.py` will print it again. At an approval point, record it only after
  the user has answered (for the blueprint and the paper: after they typed the approve command).
- If `--done` prints **Not recorded**, the step has not finished (a missing file, a failing check, an
  earlier step not done): show the message to the user; do not work around it.
- If it says **STOP**, the step is an approval point: ask the user and wait for their answer.
- It can send you back: editing `questions.json` makes the blind paper, the comparison and the PDFs
  out of date, so those steps are next again. Follow it; do not skip a step it prints.
- If what it prints disagrees with what you expected, tell the user; do not work around it.

## Workflow

### 0. Inputs

The user provides a spec file. If they have none, point them to
`${CLAUDE_SKILL_DIR}/schemas/paper-spec.template.json` and `${CLAUDE_SKILL_DIR}/schemas/paper-spec-format.md`,
and ask them to supply one. Do not
write a spec from a chat description.

Make the paper's task folder:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/new_paper.py" PATH/TO/THE/USERS/spec.json
```

It creates `papers/` if needed and a new folder named board-class-subject-date, copies the spec into
it as `spec.json`, and prints the folder's path: that is `TASK` from here on. It never reuses an
existing folder (a repeat on the same day gets `-2`, `-3`...). Exit code 2 means the spec could not be
read. To carry on with an earlier paper, use its existing `TASK` and skip this script.

Find the syllabus pack for the spec's board, class, subject and book under `syllabi/` in the
workspace: that folder is `PACK`. If there is none, look for a matching sample pack under
`${CLAUDE_SKILL_DIR}/assets/syllabi/`; if one matches, ask the user whether to copy it into
`syllabi/`, and copy it only on their yes. If there is no pack at all, a concept list must be drafted
and approved before a paper can be made: tell the user, ask for their syllabus, and make the pack
with the make-pack skill (`/exam-papers:make-pack`); then come back to this step.

The pack's concept list must be approved as it is now (gate 1); `make_blueprint.py` refuses one that
is not. If `PACK/approvals.json` has no approval of it (always so for a newly copied sample), run
```
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_concepts.py" PACK/concepts.json
```
and show the user its output verbatim and, per chapter, each concept's tag, kinds and maxMarks, and
every point in `notTested` with its reason. Ask them to type `/exam-papers:approve concepts` (with
the pack's folder name if there are several packs), and wait. A hook validates the list and records
the approval with the list's hash; editing the list afterwards voids it. Never write
`approvals.json` and never treat "approved" in chat as an approval.

### 1. Validate the spec

```
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_paper_spec.py" TASK/spec.json
```

- Exit code 1, errors (`[S1]`...): show them verbatim and stop. Suggest fixes; the user decides.
- Exit code 0: show any warnings and info, then continue.

### 2. Make the blueprint (approval point)

```
python3 "${CLAUDE_SKILL_DIR}/scripts/make_blueprint.py" TASK/spec.json --concepts PACK/concepts.json
```

It writes
`TASK/blueprint.json`. Show the user, per question: number, section, chapter, concept, marks, kind
and difficulty; the balance figures; and any `[Q14]` warnings. Then ask them to approve it by typing
`/exam-papers:approve blueprint`, and wait. The approval holds only for the blueprint as it is when
they type it: any change to the file afterwards voids it. If the user wants a different blueprint,
the spec is what changes (rerun the script); never hand-edit slots.
`make_blueprint.py` will not overwrite an approved blueprint without `--force`; do not use `--force`
unless the user asks for it.

### 3. Draft `questions.json` (writer subagent)

Start the `exam-papers:writer` subagent by its type (never paste its instructions into a
general-purpose subagent) in **draft** mode. Its prompt gives these paths, each written out in full:
`TASK/blueprint.json`, `TASK/spec.json`, `PACK/concepts.json`, `PACK/syllabus.md`,
`${CLAUDE_SKILL_DIR}/schemas/question-format.md`, the script
`${CLAUDE_SKILL_DIR}/scripts/check_questions.py`, and the output `TASK/questions.json`. The writer
writes the questions, answers, marking and diagrams (`TASK/make_diagrams.py` and its images) and runs
the check itself until it passes. Wait for it to finish.

You never write or edit `TASK/questions.json` yourself: the writer does, in draft mode here and in
revise mode at step 5.5.

### 4. Check

```
python3 "${CLAUDE_SKILL_DIR}/scripts/check_questions.py" TASK/questions.json
```

The writer ran this before handing back, so it should pass (exit code 0): show the user the warnings.
If it fails (exit code 1), show the errors verbatim and ask the user how to go on; do not fix them
yourself.

### 5. Review (a loop of up to 3 rounds)

Each round: the blind paper, the blind solver, the comparison, the reviewer, then closing the round.
`review_status.py` then says what happens next: the user decides (gate 3), the writer revises
(automatically, for errors and accepted findings), or the paper is ready for approval. `next_step.py`
prints each step in turn; the loop comes from the steps' conditions, never from you skipping ahead.
File formats: `${CLAUDE_SKILL_DIR}/schemas/review-format.md`. Everything goes in `TASK/review/`.

1. **Prepare the blind paper.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/extract_paper.py" TASK/questions.json
   ```
   This writes `TASK/review/solver-input.json`: the paper as a student sees it, with no answers.
2. **Blind solver.** Start the `exam-papers:blind-solver` subagent by its type (its definition limits
   its tools; never paste its instructions into a general-purpose subagent). Its prompt is only two paths: `TASK/review/solver-input.json` (its input) and
   `TASK/review/solver-answers.json` (its output). Give it nothing else: do not paste in
   `questions.json`, the key or any answer.
3. **Compare.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/compare_solutions.py" TASK/questions.json TASK/review/solver-answers.json --out TASK/review/compare-output.txt
   ```
   Exit code 1 means mismatches (`[V1]`-`[V5]`), not a failure of the script. The output also lists
   problems the solver reported (`[V6]`) and the theory parts side by side. Show it to the user
   verbatim.
4. **Reviewer (every round).** Start the `exam-papers:reviewer` subagent by its type (never paste
   its instructions into a general-purpose subagent). Its prompt gives these paths, each written out
   in full: `TASK/questions.json`, `TASK/spec.json`, `PACK/concepts.json`, `PACK/syllabus.md`,
   `${CLAUDE_SKILL_DIR}/schemas/question-format.md`, `${CLAUDE_SKILL_DIR}/schemas/review-format.md`,
   the script `${CLAUDE_SKILL_DIR}/scripts/render_review.py`, and the output path
   `TASK/review/reviewer-report.json`; also paste in the full output of step 3. From round 2 on
   (`TASK/review/rounds.json` lists the closed rounds; N is the last), it also gets
   `TASK/review/rounds/N/reviewer-report.json` (its previous report),
   `TASK/review/writer-response.json`, `TASK/review/decisions.json` if there is one, and the output
   of
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/review_status.py" TASK --changes
   ```
   pasted in: what changed since round N. The reviewer writes its findings, every earlier one with
   its status, and runs `render_review.py` on them, which writes `TASK/review/reviewer-report.html`.
   When it has finished, print the findings with
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/render_review.py" TASK/review/reviewer-report.json --print
   ```
   and show that output to the user verbatim, then send them `TASK/review/reviewer-report.html`.
   Exit code 1 means the reviewer's file breaks the format: tell the user, and do not fix it yourself.
5. **Close the round.**
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/review_status.py" TASK --close-round
   ```
   It saves the round in `TASK/review/rounds/N/`. Exit code 1 means the report dropped an earlier
   finding or changed a severity without a note: show the message, and start the reviewer again with
   it. Then run `review_status.py TASK` and show its summary to the user.
6. **Decide (approval point, only when the summary lists something under "Teacher to decide" or
   "Disputes").** Errors are not asked about: the writer fixes them. Show each listed warning and
   suggestion. A dispute is a finding still open after round 3: show the reviewer's finding and the
   writer's response side by side; `accept` gives the writer one more round (ask for the user's
   instruction), `reject` leaves the paper as it is (to fix it themselves, the user edits
   `questions.json` and rejects it). Then ask the user to type their decision, covering every listed
   finding at once, for example
   `/exam-papers:decide accept R2 R4 reject R5`, and wait. A hook checks it and records it in
   `TASK/review/decisions.json`; never write that file yourself (a hook blocks it), and never treat a
   decision given in chat as recorded. Reasons and instructions stay in chat: pass the instructions
   to the writer. Only `R` IDs: the reviewer has turned every solver mismatch into a finding or listed
   it as dismissed; if the user disagrees with a dismissal, say so and ask how to proceed. A rejected
   finding stays closed for good; an accepted one is fixed by the writer like an error. The user may
   also reject an open error they think the reviewer got wrong (`/exam-papers:decide reject R1`),
   even while the writer is due to fix it.
7. **Revise (writer, no approval needed).** When the summary lists IDs under "Writer to address" or
   "Writer to revert", start the `exam-papers:writer` subagent by its type in **revise** mode. Its
   prompt gives those IDs (for each one to revert, the before and after text from
   `review_status.py TASK --fixes`), any instruction the user gave, and these paths in full: `TASK/questions.json`,
   `TASK/review/reviewer-report.json`, `TASK/blueprint.json`, `TASK/spec.json`,
   `PACK/concepts.json`, `PACK/syllabus.md`, `${CLAUDE_SKILL_DIR}/schemas/question-format.md`, the
   script `${CLAUDE_SKILL_DIR}/scripts/check_questions.py`, and the output
   `TASK/review/writer-response.json`. Never give the writer the comparison output or the solver's
   answers. When it has finished, show the user `TASK/review/writer-response.json` and carry on
   without waiting: the next round starts (the user can interrupt at any time).
8. **Approve the paper (approval point).** When nothing is open, show the user the finished paper
   (every question with its answer and marking) and every change made in the review loop:
   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/review_status.py" TASK --fixes
   ```
   Show its output verbatim: each change is labelled AUTOMATIC (an error fixed without asking),
   ACCEPTED BY YOU or UNDONE BY YOU, with the reviewer's verdict and the text before and after, and
   it lists any change no writer response accounts for. Ask the user to type
   `/exam-papers:approve paper`, and wait. To undo a fix instead, the user types
   `/exam-papers:decide reject ID`: the finding is closed for good, the writer restores the text
   (step 7), and a new round reviews the result. Any later change to `TASK/questions.json` voids this
   approval and starts a new review round; the 3-round cap still applies, so anything the reviewer
   flags in it comes to the user as a dispute.

A mismatch is not proof that the key is wrong: the solver may be wrong, or the question unclear.
The reviewer works out which; if the user doubts its call, discuss it with them.

### 6. Build

```
python3 "${CLAUDE_SKILL_DIR}/scripts/render.py" TASK/questions.json
```

It checks the questions again, then writes the question paper and answer key into `TASK`. Exit code 1
means the questions failed `check_questions.py` or no usable font was found. If it warns about missing
diagram images, produce them and run it again. Open both PDFs and look at them before delivering.

### 7. Deliver

Send both PDFs to the user. Say in one or two lines what was made, the path of `TASK`, and any
warnings that remain.

## When something goes wrong

- A script exits with code 2: an input file is missing or not valid JSON. Say which.
- A `[Q8]` concept error: the question uses a tag that is not in the concept list for its chapter.
  The writer must use the blueprint's tag; start it in revise mode with the error.
- `render.py` reports a missing glyph: the installed font lacks a character; tell the user which.
- Anything outside the spec (a change to the pattern, tolerances or concept list): stop and ask.
