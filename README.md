# Exam Paper Generator

A Claude plugin, **exam-papers**, that makes exam question papers and teacher answer keys (two PDFs)
from a syllabus and a paper spec. Scripts plan and check the structure, Claude writes the wording, and
a blind solver and an independent reviewer check the paper before the teacher approves it. The goal,
the architecture and every decision are in [`docs/harness-design.md`](docs/harness-design.md).

## Install

The repo is a plugin marketplace. In Claude Code:

```
/plugin marketplace add /path/to/exam-paper-generator
/plugin install exam-papers@exam-paper-generator
```

Installed from a local folder, the plugin's files are read straight from this repo, so an edit takes
effect after `/reload-plugins` or in the next session. The plugin needs Python 3 with the packages in
`requirements.txt` (reportlab for the PDFs, matplotlib for diagrams).

## Using it

Work in a folder of your own (the **workspace**), not in this repo. It holds:

- `syllabi/<pack>/`: a syllabus (`syllabus.md`) and its approved concept list (`concepts.json`). A
  sample pack, ICSE Class 9 Physics (Selina), ships with the skill and is copied in on request.
- `papers/<task>/`: one folder per paper, `papers/<board>-<class>-<subject>-<date>/`, made by
  `new_paper.py`; it holds the spec, blueprint, questions, review files and both PDFs. An existing
  folder is never reused (a second paper on the same day gets `-2`).

Give Claude your `spec.json` (format and template in the skill's `schemas/`) and invoke
`/exam-papers:make-paper`.

## Workflow

The steps run one at a time, in the order listed in the skill's `workflow.json`. Its
`scripts/next_step.py TASK` checks the paper's task folder and prints the one step that may run next
(approval points say STOP); `SKILL.md` has Claude run it before every step. When a step finishes,
`next_step.py TASK --done STEP_ID` records the hashes of its files in `TASK/state.json` and appends to
`TASK/run.jsonl`; a step is done while its inputs are unchanged, so copying a folder or re-saving a
file does not change where the paper is. At the two approval points you type
`/exam-papers:approve blueprint` and `/exam-papers:approve paper`; a hook records each one, with the
file's hash, in `TASK/approvals.json`, and editing an approved file voids its approval.

1. **Paper spec**: the user supplies `spec.json`; `validate_paper_spec.py` checks it (rules S1–S19).
2. **Blueprint**: `make_blueprint.py` builds `blueprint.json` from the spec and the approved concept
   list: one slot per question part (chapter, marks, kind, difficulty, concept, MCQ answer letter). It
   first checks the concept list against its syllabus (`validate_concepts.py`, rules C1–C6). The user
   approves the blueprint.
3. **Draft**: Claude writes `questions.json` from the approved blueprint (wording only).
4. **Check**: `check_questions.py` runs hard rules (block) and soft rules (warn), Q1–Q15.
5. **Review**: `extract_paper.py` writes the paper without answers; the `exam-papers:blind-solver`
   agent solves it; `compare_solutions.py` compares its answers with the key (rules V1–V6); the
   `exam-papers:reviewer` agent writes its findings as JSON and runs `render_review.py`, which makes
   an HTML report. Reports are shown verbatim.
6. **Fix**: apply only the fixes the user accepts.
7. **Build**: `render.py questions.json` renders the question paper and the answer key into the task
   folder. It runs `check_questions.py` first and refuses to build if a hard rule fails.

## Development

Install the packages from the repo root: `pip3 install -r requirements-dev.txt` (adds pypdf, which the
PDF-content tests need; they are skipped without it). Run all tests from the repo root:
`python3 -m unittest discover tests`. The tests use fixed data in `tests/test_data/` (a small 21-mark
paper, plus a 50-mark spec for the blueprint generator), never `examples/` or generated papers.

## Layout

```
.claude-plugin/marketplace.json     # makes this repo a marketplace listing the plugin
plugins/exam-papers/                # the plugin: the only part that is installed
  .claude-plugin/plugin.json
  agents/                           # blind-solver.md, reviewer.md (the two review subagents)
  commands/approve.md               # /exam-papers:approve blueprint|paper (typed by the teacher)
  hooks/                            # hooks.json + approve.py: record typed approvals, guard approvals.json
  skills/make-paper/
    SKILL.md                        # main workflow
    workflow.json                   # the steps in order: who does each, approval points, when done
    schemas/                        # spec (S-rules), questions + blueprint (Q-rules), concept list
                                    # (C-rules), review files (V-rules); spec template
    scripts/                        # validate_paper_spec, validate_concepts, make_blueprint,
                                    # check_questions, render, new_paper, extract_paper,
                                    # compare_solutions, next_step, render_review, spec_types,
                                    # approvals, task_files
    assets/syllabi/icse9-physics-selina/   # sample pack: syllabus.md, concepts.json (approved)
docs/harness-design.md              # goal, architecture, decisions D1–D19
examples/icse9-physics-ch1-5/       # example paper: spec + draft blueprint
tests/                              # unit tests; tests/test_data/ holds their fixed data
requirements.txt, requirements-dev.txt
```

## Decisions so far

- Sections are a list; each has `questionsOffered`, `questionsToAttempt`,
  `marksPerQuestion` and `sectionTotal` (kept on purpose as a cross-check).
- Balance rules (chapters, numerical/theory, difficulty) are **soft** with tolerances:
  chapter weightage ±5 marks, numerical/theory ±5%, difficulty ±10%.
- Balance is measured on marks **offered**, not attempted.
- Every chapter must appear in the compulsory section.
- Totals, sub-part sums, question counts, constants and "no hard questions" are **hard** rules.
- Questions: text markup is HTML-style (`<sup>`, `<sub>`, `<b>`, `<i>`); every numerical answer has a
  `computed` expression that a script evaluates; concept tags come from a fixed list per chapter;
  numerical/theory and difficulty are tagged per part (one kind per part); parts nest one level at most.
- Pipeline: `spec.json` (user-supplied, checked by script) → `blueprint.json` (script,
  approved by user) → `questions.json` (Claude, checked by script and reviewers) → PDFs (script).
- Difficulty target stays 50/50 ± 10%.
- Determinism: code decides structure (blueprint, marks, concepts, arithmetic); Claude writes the wording.
- The concept list is drafted once from the syllabus, checked for coverage, approved by a teacher and
  then frozen. Each concept records its syllabus `source`, the `kinds` it supports (encoding syllabus
  limits such as "no numerical problems on callipers and screw gauge") and `maxMarks`.
- Concepts are organised by book chapter; the syllabus numbers its sections differently
  (syllabus 4 "Fluids" = book chapters 4 and 5; syllabus 5–8 = book chapters 6–10).
- The blueprint names a concept for every part, so the approved blueprint says what each part tests.
- Rendering: everything printed that is not question wording comes from the spec (time, maximum marks,
  section headings, general instructions, constants, numbering, chapter names, what the answer key
  includes). `render.py` gates on `check_questions.py`; warnings do not block.
- Diagrams: Claude draws each image (matplotlib) when it drafts the question and saves it beside
  `questions.json`; `render.py` only places it. A missing image prints a labelled placeholder box and a
  warning at the end of the run (no flag, no failure).
- Fonts: system fonts only, nothing bundled: the first of Times New Roman, Liberation Serif, DejaVu Serif
  that is installed and has every character the paper uses (a warning names any missing glyph).
- Review: the blind solver gets its input from a script (`extract_paper.py`), which refuses to write any
  answer field, so blindness does not depend on Claude stripping things out. Numerical and MCQ answers are
  compared by script; theory answers are listed side by side for the reviewer to judge. A mismatch is a
  lead, not proof (unit and sign conventions cause false alarms).
- Output: every generated paper lives in its own folder, `papers/<board>-<class>-<subject>-<date>/`,
  made by `new_paper.py` (never reused; `-2`, `-3` on a clash). `render.py` writes the PDFs into the
  task folder itself. `examples/` is for reference papers, not new ones.
- Blueprint chapter allocation: spread evenly within each section first, then stay within the chapter
  tolerance; with 4 long questions over 5 chapters, one chapter gets no long question.

## Status

- [x] Paper spec format + `validate_paper_spec.py` (rules S1–S19)
- [x] Question and blueprint formats (rules Q1–Q15) + `check_questions.py`
- [x] Shared enums (`spec_types.py`); rule numbers in every message (`[S6] ...`, `[Q4] ...`, `[C6] ...`)
- [x] Syllabus 2026–2027 saved as the sample pack's `syllabus.md`
- [x] Concept list redrafted from the syllabus (94 concepts, all 22 syllabus sections covered)
      + `validate_concepts.py` (rules C1–C6)
- [x] `concepts.json` reviewed and approved (status: approved, now frozen)
- [x] `make_blueprint.py` + tests; first draft blueprint in `examples/icse9-physics-ch1-5/`
- [x] `render.py` + tests
- [x] `SKILL.md` reviewed and approved (user supplies the spec; no clarifying questions for now)
- [x] Review chain: `extract_paper.py`, `compare_solutions.py`, the blind-solver and reviewer agents
      (run once end to end with real subagents)
- [x] `workflow.json` + `next_step.py`: one step at a time, in a fixed order, checked against the task folder
- [x] State by content hashes (`state.json`, `run.jsonl`, `next_step.py --done`) instead of file times
- [x] Typed approvals for the blueprint and the final paper (`/exam-papers:approve`, hooks, `approvals.json`)
- [x] Unit tests moved to their own test data (`tests/test_data/`); 321 tests, all passing
- [ ] New example: approve the `icse9-physics-ch1-5` blueprint, write its questions, review, render

Open question: the syllabus includes spherical mirrors (with mirror-formula numericals) and
electromagnets; check whether the book edition covers them (concepts are included for now).
