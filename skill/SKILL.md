---
name: exam-paper-generator
description: Generate an exam question paper and a teacher answer key (two PDFs) from a paper spec JSON. Use when the user supplies a paper spec (spec.json) or asks for an exam paper, question paper or answer key for a board, class and book that has an approved concept list.
---

# Exam paper generator

Produces a question paper and a teacher answer key as PDFs. The paper is defined by a **paper spec**
the user provides. Scripts decide the structure and check the result; you write only the wording.

## Ground rules

- **Code decides structure, you write wording.** Chapters, marks, kinds, difficulty and concepts for
  every question come from `blueprint.json`. Never change a slot. Arithmetic is checked by script.
- **Run exactly the scripts named in this file, with the exact paths given.** Do not write your own
  version of what a script does, do not run a script that is not listed for the step, and do not run
  scripts from `examples/`. Check the exit code of every script; stop on one this file does not expect.
- **Never assume.** If something in the spec or a script's output is unclear, ask the user.
- **One step at a time, in order.** Before every step, run `python3 skill/scripts/next_step.py TASK`
  and do only the step it prints (see "Order of work"). Never run two steps side by side: do not start
  a step, read ahead for it or prepare it while a script or subagent from an earlier step is still
  running. Wait for each subagent to finish before doing anything else. Report each step briefly, then
  run `next_step.py` again. Stop and wait at the approval points (spec errors, blueprint, fixes).
- **Show script and reviewer output verbatim** when it contains errors or findings. Do not summarise
  them away, and do not change anything because of them until the user has seen them.
- **Refer to scripts by file name** (`check_questions.py`), not "the checker".
- **Never edit an approved concept list.** If a concept is wrong or missing, tell the user; changes
  go through a reviewed diff.

## Paths

**Every path in this file is relative to the project root** (the folder that contains `skill/`,
`agents/`, `examples/` and `output/`). Run every command from the project root, and write files
into the user's own folder on their computer, not only the cloud workspace.

`TASK` means the paper's task folder, `output/<board>-<class>-<subject>-<date>/` (for example
`output/icse-9-physics-2026-10-27/`). Step 0 creates it and prints its path. `spec.json`,
`blueprint.json`, `questions.json`, diagram images, `review/` and the two PDFs all live in `TASK`.

### Scripts used in the workflow

| Step | Script (exact path) | What it does | Writes |
|---|---|---|---|
| every | `skill/scripts/next_step.py` | Prints the one step that may run next (order from `skill/workflow.json`) | nothing |
| 0 | `skill/scripts/new_paper.py` | Makes `TASK` and copies the user's spec into it | `TASK/spec.json` |
| 1 | `skill/scripts/validate_paper_spec.py` | Checks the spec (rules S1-S19) | nothing |
| 2 | `skill/scripts/make_blueprint.py` | Plans every question slot from the spec and concept list | `TASK/blueprint.json` |
| 4 | `skill/scripts/check_questions.py` | Checks the questions (rules Q1-Q15) | nothing |
| 5.1 | `skill/scripts/extract_paper.py` | Makes the paper with no answers for the blind solver | `TASK/review/solver-input.json` |
| 5.3 | `skill/scripts/compare_solutions.py` | Compares the solver's answers with the key (rules V1-V6) | `TASK/review/compare-output.txt` |
| 5.4 | `skill/scripts/render_review.py` | Checks the reviewer's findings and makes the HTML report (run by the reviewer; rerun to print the findings) | `TASK/review/reviewer-report.html` |
| 6 | `skill/scripts/render.py` | Builds the question paper and answer key PDFs | two PDFs in `TASK` |

Files that are **not** run in the workflow: `skill/scripts/spec_types.py` (a library the other scripts
import) and `skill/scripts/validate_concepts.py` (only when the user asks you to check a concept list).

### Other files used

| What | Exact path |
|---|---|
| Spec format and template | `skill/schemas/paper-spec-format.md`, `skill/schemas/paper-spec.template.json` |
| Question format (read before step 3) | `skill/schemas/question-format.md` |
| Review file formats | `skill/schemas/review-format.md` |
| Concept list format | `skill/schemas/concept-list-format.md` |
| ICSE Class 9 Physics (Selina) concept list | `skill/references/icse9-physics-selina/concepts.json` |
| ICSE Class 9 Physics (Selina) syllabus | `skill/references/icse9-physics-selina/syllabus.md` |
| Blind-solver prompt | `agents/blind-solver.md` |
| Reviewer prompt | `agents/reviewer.md` |

Another board, class or book has its own folder under `skill/references/`.

## Order of work

The steps, their order and the approval points are listed in `skill/workflow.json`.
`skill/scripts/next_step.py` reads it, looks at what is in `TASK`, and prints the one step that may
run next:

```
python3 skill/scripts/next_step.py TASK
```

- Run it before every step (from step 1 on; before step 0 there is no `TASK`). Do the step it prints,
  and nothing else, until that step has finished.
- If it says **STOP**, the step is an approval point: ask the user and wait for their answer.
- It can send you back: editing `questions.json` makes the blind paper, the comparison and the PDFs
  out of date, so those steps are next again. Follow it; do not skip a step it prints.
- If what it prints disagrees with what you expected, tell the user; do not work around it.

## Workflow

### 0. Inputs

The user provides a spec file. If they have none, point them to `skill/schemas/paper-spec.template.json`
and `skill/schemas/paper-spec-format.md`, or an existing example, and ask them to supply one. Do not
write a spec from a chat description.

Make the paper's task folder:

```
python3 skill/scripts/new_paper.py PATH/TO/THE/USERS/spec.json
```

It creates `output/` if needed and a new folder named board-class-subject-date, copies the spec into
it as `spec.json`, and prints the folder's path: that is `TASK` from here on. It never reuses an
existing folder (a repeat on the same day gets `-2`, `-3`...). Exit code 2 means the spec could not be
read. To carry on with an earlier paper, use its existing `TASK` and skip this script.

Find the concept list for the spec's board, class, subject and book under `skill/references/`
(for ICSE Class 9 Physics, Selina: `skill/references/icse9-physics-selina/concepts.json`). If there is
none, stop: a concept list must be drafted and approved before a paper can be made.

### 1. Validate the spec

```
python3 skill/scripts/validate_paper_spec.py TASK/spec.json
```

- Exit code 1, errors (`[S1]`...): show them verbatim and stop. Suggest fixes; the user decides.
- Exit code 0: show any warnings and info, then continue.

### 2. Make the blueprint (approval point)

```
python3 skill/scripts/make_blueprint.py TASK/spec.json --concepts skill/references/icse9-physics-selina/concepts.json
```

(Use the concept list found in step 0 if the paper is not ICSE Class 9 Physics.) It writes
`TASK/blueprint.json` with status `"draft"`. Show the user, per question: number, section, chapter,
concept, marks, kind and difficulty; the balance figures; and any `[Q14]` warnings. Ask for approval.
On approval, change only `"status"` to `"approved"` in `TASK/blueprint.json`. If the user wants a
different blueprint, the spec is what changes (rerun the script); never hand-edit slots.
`make_blueprint.py` will not overwrite an approved blueprint without `--force`; do not use `--force`
unless the user asks for it.

### 3. Draft `questions.json`

Read `skill/schemas/question-format.md`, then write `TASK/questions.json` from the approved blueprint.
Its `spec` field is `spec.json` and its `conceptList` field is the relative path from `TASK` to the
concept list (copy it from `TASK/blueprint.json`). For every question:

- Copy `number`, `section`, `chapter`, `concepts`, `marks`, and every part's `label`, `marks`,
  `kind`, `difficulty` and `concept` exactly from the blueprint (rule Q15). Add the wording.
- `text`/`stem`: clear, self-contained, at the level of the class and book. Test only the part's
  `concept`, within its `kind`. Do not go beyond the syllabus
  (`skill/references/icse9-physics-selina/syllabus.md` for this book).
- `answer`: the model answer with working; `marking`: items that add up to the part's marks.
- Every numerical part and numerical MCQ has `computed`: an `expression` using plain numbers
  (spec constants as numbers) and the `value` it gives. Compute with a script, not in your head.
- MCQs: one correct option, placed at the letter the blueprint's `correctOption` gives (rule Q15);
  in a numerical MCQ it starts with the computed value (rule Q4). Wrong options should be real mistakes (a unit slip, an inverted ratio);
  `explanation` says why the answer is right and why the tempting wrong options are wrong.
- Use only the text markup in the format doc. Use the spec's constants. Respect the spec's
  `diagrams` setting.
- Use clean numbers. A question must be solvable from the paper alone.
- **Diagrams:** draw each with a small matplotlib script saved as `TASK/make_diagrams.py`, save each
  PNG in `TASK` beside `questions.json`, and name it in the question's `diagram` (paper) or
  `answerDiagram` (key), with a `description` that says exactly what it shows.
- Do not repeat a concept across questions beyond what the blueprint already assigns.

Write the file one section at a time.

### 4. Check

```
python3 skill/scripts/check_questions.py TASK/questions.json
```

Exit code 1: fix every error (`[Q...]`) and rerun until it passes. Exit code 0: show the user the
warnings.

### 5. Review

Two independent checks; neither edits `questions.json`. File formats:
`skill/schemas/review-format.md`. Everything goes in `TASK/review/`.

1. **Prepare the blind paper.**
   ```
   python3 skill/scripts/extract_paper.py TASK/questions.json
   ```
   This writes `TASK/review/solver-input.json`: the paper as a student sees it, with no answers.
2. **Blind solver.** Spawn a subagent whose prompt is the full text of `agents/blind-solver.md` plus
   two paths: `TASK/review/solver-input.json` (its input) and `TASK/review/solver-answers.json` (its
   output). Give it nothing else: do not paste in `questions.json`, the key or any answer.
3. **Compare.**
   ```
   python3 skill/scripts/compare_solutions.py TASK/questions.json TASK/review/solver-answers.json --out TASK/review/compare-output.txt
   ```
   Exit code 1 means mismatches (`[V1]`-`[V5]`), not a failure of the script. The output also lists
   problems the solver reported (`[V6]`) and the theory parts side by side. Show it to the user
   verbatim.
4. **Reviewer.** Spawn a subagent whose prompt is the full text of `agents/reviewer.md` plus these
   paths: `TASK/questions.json`, `TASK/spec.json`, the concept list, the syllabus
   (`skill/references/icse9-physics-selina/syllabus.md` for this book), and the output path
   `TASK/review/reviewer-report.json`; also paste in the full output of step 3. The reviewer writes
   its findings to that file and runs `skill/scripts/render_review.py` on it, which writes
   `TASK/review/reviewer-report.html`. When it has finished, print the findings with
   ```
   python3 skill/scripts/render_review.py TASK/review/reviewer-report.json
   ```
   and show that output to the user verbatim, then send them `TASK/review/reviewer-report.html`.
   Exit code 1 means the reviewer's file breaks the format: tell the user, and do not fix it yourself.
   The reviewer runs once, before the first fix decision.
5. **Fix (approval point).** Ask the user which findings and mismatches to fix, and write their answer
   to `TASK/review/fixes.json` as `{"accepted": ["R1", ...], "rejected": ["R12", ...]}` (an empty
   `accepted` list if they want none). Apply only the accepted fixes to `TASK/questions.json`. Any
   change sends the paper back through steps 4 and 5.1-5.3 (`next_step.py` prints them in turn); if
   the new comparison finds mismatches, the user decides again.

A mismatch is not proof that the key is wrong: the solver may be wrong, or the question unclear.
Work out which with the user.

### 6. Build

```
python3 skill/scripts/render.py TASK/questions.json
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
  Use the blueprint's tag.
- `render.py` reports a missing glyph: the installed font lacks a character; tell the user which.
- Anything outside the spec (a change to the pattern, tolerances or concept list): stop and ask.
