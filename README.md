# Exam Paper Generator

A Claude skill (plus supporting agents and scripts) that produces exam question papers
and teacher answer keys from a structured spec.

## Workflow (target)

The steps run one at a time, in the order listed in `skill/workflow.json`.
`skill/scripts/next_step.py TASK` checks the paper's task folder and prints the one step that may run
next (approval points say STOP); `SKILL.md` has Claude run it before every step.

1. **Paper spec**: for now the user supplies `spec.json` (format: `skill/schemas/paper-spec-format.md`,
   template and examples beside it); Claude does not write it from a chat description. Validate it
   with `skill/scripts/validate_paper_spec.py`. (Later option, not built: a flat `paper-request.json` →
   `make_spec.py` → a plain-English readback of the spec that the user confirms.)
2. **Blueprint**: `skill/scripts/make_blueprint.py` builds `blueprint.json` from the spec and the
   approved concept list: one slot per question part (chapter, marks, kind, difficulty, concept).
   It first checks the concept list against its syllabus (`validate_concepts.py`, rules C1–C6) and
   refuses to run if the list does not name its syllabus file. The user approves the blueprint.
3. **Draft**: Claude writes `questions.json` from the approved blueprint (wording only).
4. **Check**: `skill/scripts/check_questions.py` runs hard rules (block) and soft rules (warn).
5. **Review**: `extract_paper.py` writes the paper without answers; a blind-solver subagent solves it;
   `compare_solutions.py` compares its answers with the key (rules V1–V6); an independent reviewer
   subagent writes its findings as JSON and runs `render_review.py`, which makes an HTML report.
   Reports are shown verbatim (`skill/schemas/review-format.md`).
6. **Fix**: apply only the fixes the user accepts.
7. **Build**: `skill/scripts/render.py questions.json` renders the question paper and the answer key
   (two PDFs, in the same task folder as `questions.json`). It runs `check_questions.py` first and
   refuses to build if a hard rule fails.

Each paper has its own task folder, made by `skill/scripts/new_paper.py spec.json` under the project's
`output/` folder: `output/<board>-<class>-<subject>-<date>/` (e.g. `output/icse-9-physics-2026-10-27/`).
It holds the spec, blueprint, `questions.json`, diagram images, `review/` and both PDFs. An existing
folder is never reused or overwritten (a second paper on the same day gets `-2`).

Install the Python packages from the project root: `pip3 install -r requirements.txt` to make papers
(reportlab for the PDFs, matplotlib for diagrams), or `pip3 install -r requirements-dev.txt` to also run
the tests (adds pypdf, which the PDF-content tests in `test_render.py` need; they are skipped without it).

Run all tests from the project root: `python3 -m unittest discover tests`. The tests check the scripts
against fixed test data in `tests/test_data/` (a small 21-mark test paper, plus a 50-mark spec for the
blueprint generator), never against `examples/` or generated papers.

## Layout

```
skill/                          # what gets installed in Claude
  SKILL.md                      # main workflow (approved)
  schemas/
    paper-spec-format.md        # spec fields and rules S1–S19
    paper-spec.template.json
    question-format.md          # questions + blueprint fields and rules Q1–Q15
    concept-list-format.md      # concept list fields and rules C1–C6
    review-format.md            # blind-solver input/answers, reviewer report, rules V1–V6
  scripts/
    spec_types.py               # shared enums
    validate_paper_spec.py      # spec → S-rules
    validate_concepts.py        # concept list vs syllabus → C-rules
    make_blueprint.py           # spec + concept list → blueprint
    check_questions.py          # questions vs spec, blueprint, concept list → Q-rules
    render.py                   # questions + spec → question paper and answer key PDFs
    new_paper.py                # spec → new output/<board>-<class>-<subject>-<date>/ folder
    extract_paper.py            # questions → paper with no answers (blind solver's input)
    compare_solutions.py        # solver answers vs key → V-rules
    next_step.py                # task folder → the one step that may run next (reads workflow.json)
    render_review.py            # reviewer's findings (JSON) → checked → HTML report
  workflow.json                 # the steps in order: who does each, approval points, when it is done
  references/
    icse9-physics-selina/
      syllabus.md               # ICSE Class 9 Physics syllabus 2026–2027 (from the user)
      concepts.json             # 94 concepts, chapters 1–10, drafted from the syllabus (status: approved)
agents/                         # blind-solver.md, reviewer.md (prompts for the two review subagents)
output/                         # one task folder per generated paper (made by new_paper.py)
examples/
  icse9-physics-ch1-5/          # example paper: spec + draft blueprint (questions to come)
requirements.txt                # packages needed to make a paper (reportlab, matplotlib)
requirements-dev.txt            # requirements.txt + pypdf for the tests
tests/                          # unit tests for the scripts: python3 -m unittest discover tests
  helpers.py                    # TEST_DATA path shared by the tests
  test_data/                    # fixed test data, used only by the tests:
                                #   spec, concepts, syllabus, blueprint, questions, vt_graph.png (a
                                #   21-mark test paper) and spec-50-marks.json (for make_blueprint)
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
- Output: every generated paper lives in its own folder, `output/<board>-<class>-<subject>-<date>/`,
  made by `new_paper.py` (never reused; `-2`, `-3` on a clash). `render.py` writes the PDFs into the
  task folder itself. `examples/` is for reference papers, not new ones.
- Blueprint chapter allocation: spread evenly within each section first, then stay within the chapter
  tolerance; with 4 long questions over 5 chapters, one chapter gets no long question.

## Status

- [x] Paper spec format + `validate_paper_spec.py` (rules S1–S19)
- [x] Question and blueprint formats (rules Q1–Q15) + `check_questions.py`
- [x] Shared enums (`spec_types.py`); rule numbers in every message (`[S6] ...`, `[Q4] ...`, `[C6] ...`)
- [x] Syllabus 2026–2027 saved as `references/icse9-physics-selina/syllabus.md`
- [x] Concept list redrafted from the syllabus (94 concepts, all 22 syllabus sections covered)
      + `validate_concepts.py` (rules C1–C6)
- [x] `concepts.json` reviewed and approved (status: approved, now frozen)
- [x] `make_blueprint.py` + tests; first draft blueprint in `examples/icse9-physics-ch1-5/`
- [x] `render.py` + tests
- [x] `SKILL.md` reviewed and approved (user supplies the spec; no clarifying questions for now)
- [x] Review chain: `extract_paper.py`, `compare_solutions.py`, `agents/blind-solver.md`, `agents/reviewer.md`
      (run once end to end with real subagents)
- [x] `workflow.json` + `next_step.py`: one step at a time, in a fixed order, checked against the task folder
- [x] Unit tests moved to their own test data (`tests/test_data/`); 285 tests, all passing
- [ ] New example: approve the `icse9-physics-ch1-5` blueprint, write its questions, review, render

Open question: the syllabus includes spherical mirrors (with mirror-formula numericals) and
electromagnets; check whether the book edition covers them (concepts are included for now).
