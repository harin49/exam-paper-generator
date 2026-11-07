# Harness design

The exam-papers plugin makes an exam paper and its answer key from a syllabus and a paper spec.
Claude writes the wording; everything around it, described here, makes the result checkable and
repeatable: scripts that decide and check structure, a step order enforced from files, hooks that
block what the rules forbid, independent agents, and the teacher's typed approvals. The diagrams
are in [architecture.md](architecture.md) and [review-loop.md](review-loop.md).

## How a run is driven

The host app (Claude Code, or Cowork) runs the loop: it calls the model, runs tools, starts subagents
and fires hooks. The plugin supplies the parts it runs, and there is no orchestrator of our own. The
cost: hooks can block a wrong action, but cannot force the right next one, so the step order is made
checkable instead.

- **Skills.** `make-paper/SKILL.md` is the playbook: the ground rules, then how to do each step.
  `make-pack/SKILL.md` turns a syllabus into a syllabus pack.
- **`workflow.json`** lists the steps in order, who does each (a script, an agent, Claude or the
  teacher) and when each is done:
  `new_paper` → `validate_spec` → `make_blueprint` → `approve_blueprint` → `draft_questions` →
  `check_questions` → `extract_paper` → `blind_solver` → `compare_solutions` → `reviewer` →
  `close_round` → `decide_fixes` → `apply_fixes` → `approve_paper` → `render` → `deliver`.
- **`next_step.py TASK`** reads the workflow and the task folder and prints the one step that may run
  next. Claude runs it before every step. "Done" is worked out from files, never remembered: a file
  exists, a check script passes, an approval matches its file, or a recorded step's inputs are
  unchanged. So the order cannot be skipped, and editing an earlier file sends the paper back (an
  edited `questions.json` makes the blind paper, the comparison and the PDFs due again).
- **Recording.** Claude records agent and teacher steps with `next_step.py TASK --done STEP`, which
  refuses a step whose earlier steps or outputs are missing. The four script steps (`make_blueprint`,
  `extract_paper`, `compare_solutions`, `render`) record themselves when they succeed.
- **Rules for Claude** (in `SKILL.md`): run only the scripts named, with their exact paths; show
  script and reviewer output verbatim; never write `questions.json` (the writer does); never treat an
  approval in chat as given.

## Deterministic scripts

Code decides structure and checks every file; Claude only writes wording. Every script prints its
findings with a rule id (`[S6]`, `[Q4]`, `[C6]`, `[V2]`), and exits 0 (passed, warnings allowed),
1 (errors) or 2 (a file could not be read). The rules themselves are in the skill's `schemas/`.

**Inputs**

| Script | Reads | Guarantees |
|---|---|---|
| `number_syllabus.py` | the teacher's syllabus (Markdown or text) | `syllabus.md` with an id (`[S1]`, `[S2]`...) before every paragraph and list item; the text is otherwise unchanged |
| `validate_concepts.py` | `concepts.json`, `syllabus.md` | C1–C6: well-formed concepts, unique tags, allowed kinds, and every syllabus point covered by a concept or listed in `notTested` with a reason |
| `validate_paper_spec.py` | `spec.json` | S1–S21: every field present and valid, totals add up, targets add to 100, and the pattern can balance (it prints the chapter targets and the paper's difficulty mix) |
| `new_paper.py` | `spec.json` | a new task folder `papers/<board>-<class>-<subject>-<date>/`, never reusing an old one |

**Planning**

| Script | Reads | Guarantees |
|---|---|---|
| `make_blueprint.py` | the spec and the pack's **approved** concept list | `blueprint.json`: every question's chapter, marks, parts, kind, difficulty, concept and MCQ answer letter. It refuses an unapproved concept list, leaves out `excludedConcepts`, gives the same blueprint for the same spec, and checks its own result with `check_questions.py`'s rules Q2–Q14 where they apply |

**Outputs**

| Script | Reads | Guarantees |
|---|---|---|
| `check_questions.py` | `questions.json`, the spec, the concept list, the approved blueprint | Q1–Q16: structure, numbering, marks that add up, every numerical answer recalculated from its formula (Q7), concepts from the list and not excluded (Q8), the structure equal to the approved blueprint (Q15), every LaTeX formula typesettable (Q16); balance as warnings (Q11–Q14) |
| `extract_paper.py` | `questions.json` | `review/solver-input.json`: only what a student sees. It refuses to write any answer field, so the solver's blindness does not depend on Claude |
| `compare_solutions.py` | the key, the solver's answers | V1–V6: MCQ and numerical mismatches (values within 1%), likely unit or sign slips, unanswered parts, problems the solver reported. Theory answers are listed side by side for the reviewer |
| `review_status.py` | `review/` | where the review loop stands (`close`, `decide`, `revise`, `done`); closes rounds; lists every automatic fix for the final approval (`--fixes`) |
| `render_review.py` | `review/reviewer-report.json` | the findings as an HTML page |
| `render.py` | `questions.json`, the spec | both PDFs, only if `check_questions.py` finds no error. Everything printed that is not wording comes from the spec. Formulas are drawn with matplotlib's mathtext (no TeX needed); a missing diagram prints a placeholder and a warning |

Libraries shared by the scripts and hooks: `paper.py` (labels, part walk, printed names),
`report.py` (the report and value checks), `task_files.py` (JSON, hashes, the run log),
`approvals.py`, `spec_types.py` (fixed values) and `latex.py`.

**Syllabus packs.** A pack (`syllabi/<pack>/`) holds the numbered syllabus, its concept list and the
list's approval. Concepts are grouped by the syllabus's own units (called `chapters` in the files,
printed as "Unit"). Each concept names its syllabus point (`source`), the kinds of question it allows
(the pack declares the subject's kinds, e.g. numerical and theory) and its largest part (`maxMarks`).
Question formats are MCQ, and short and long answers with parts.

## State and audit

Every task folder carries its own state, so a paper can be stopped, copied or resumed.

- **`state.json`**: each recorded step with the SHA-256 hashes of its inputs and outputs. A step is
  done while its inputs still have those hashes. Hashes, not file times, because a copy, a
  `git checkout` or a re-save changes times but not content.
- **`run.jsonl`**: an append-only log, one JSON object per event, with times: `done`, `approved`,
  `decided` and `round_closed`. Agent calls and script results are not logged yet.
- **`approvals.json`** (in the task folder, and in each pack): gate, file, the file's hash and the
  time. The latest record for a gate counts, and only while the file still has that hash, so editing
  an approved file voids its approval.
- **`review/`**: the reviewer's report, the writer's responses, `rounds.json` (closed rounds, which
  count towards the limit), a snapshot of each round in `rounds/N/`, and `decisions.json` (the
  teacher's decisions).

## Hooks

Two hooks, in `hooks/hooks.json`, enforce what the playbook can only ask for.

**`approve.py` (`UserPromptExpansion`)** records the teacher's typed commands. This event fires only
when a command the user typed expands, and the hook also requires the plugin's command name, a
plugin source and no subagent id, so neither Claude nor a subagent can create an approval.
(`UserPromptSubmit` was not used: subagent replies arrive through it too, so a subagent writing
`/exam-papers:approve` could forge one.)

- `/exam-papers:approve concepts [PACK]` runs `validate_concepts.py` first and refuses a list with
  errors; `approve blueprint` and `approve paper` record the gate's file and hash.
- `/exam-papers:decide accept … reject … [TASK]` records the decision on that round's findings, and is
  refused until every finding waiting for the teacher is covered.
- Without a folder, a command goes to the one paper waiting for it. If none or several are, it is
  blocked, and the message lists each paper's next step.

**`guard.py` (`PreToolUse`, on Read, Grep, Glob, Write, Edit, MultiEdit, NotebookEdit and Bash)**
denies tool calls that break the rules:

| Who | Denied |
|---|---|
| Everyone (Claude and subagents) | writing `approvals.json` or `decisions.json`, and any Bash command that names them (reading uses Read) |
| Blind solver | reading anything but `solver-input.json` and its own `solver-answers.json`; writing anything else; Bash commands that name a file holding the key, the plan or the review |
| Writer | reading the solver's answers or the comparison (it learns of mismatches only from the reviewer's findings); changing `blueprint.json` |

It imports none of the skill's scripts, so the check before each tool call stays cheap. Its limit:
Bash commands are matched only by the file names they contain, so it guards against mistakes, not a
determined adversary.

## Agents

Main Claude orchestrates: it runs the steps, talks with the teacher and passes work between roles.
Three plugin agents do the rest. Each is started by its type (`exam-papers:writer`...), so its tool
list holds; `guard.py` limits its files.

| Agent | Tools | Sees | Writes |
|---|---|---|---|
| `writer` | Read, Write, Edit, Bash | the approved blueprint, the spec, the pack, the question format, the reviewer's findings | `questions.json`, diagram images and `make_diagrams.py`, `review/writer-response.json`. It runs `check_questions.py` itself before handing back, and answers each finding `fixed` or `disagree` |
| `blind-solver` | Read, Write, Bash | only the blind paper (`solver-input.json`) | `review/solver-answers.json` |
| `reviewer` | Read, Write, Bash | the paper and key, the spec, the pack, the comparison | `review/reviewer-report.json` (and its HTML). It turns every solver mismatch into a finding or dismisses it with a reason, and never edits the paper |

How their work loops until the paper is ready is in [review-loop.md](review-loop.md).

## Teacher gates

Each gate is passed only by a command the teacher types (see Hooks).

| Gate | When | Command | What the teacher approves |
|---|---|---|---|
| 1. Concept list | once per pack (once per paper in cloud Cowork) | `/exam-papers:approve concepts` | the concepts drafted from the syllabus |
| 2. Blueprint | every paper, before any wording | `/exam-papers:approve blueprint` | each question's unit, concept, marks, kind and difficulty |
| 3. Findings | after a review round with warnings, suggestions or disputes | `/exam-papers:decide accept … reject …` | which findings the writer addresses |
| 4. Final paper | after review, before the PDFs | `/exam-papers:approve paper` | the reviewed paper and key, and every automatic fix (any can be undone) |

The spec is not a gate: the teacher writes it, and `validate_paper_spec.py` checks it.

## Tests

`python3 -m unittest discover tests` from the repo root ([development.md](development.md) has the
setup). The tests use fixed data in `tests/test_data/` (a small 21-mark paper with its spec, concept
list, syllabus and blueprint, and a 50-mark spec for the blueprint generator), never `examples/` or
generated papers.

| Test file | Covers |
|---|---|
| `test_validate_paper_spec.py`, `test_validate_concepts.py`, `test_number_syllabus.py` | the input checks, rule by rule |
| `test_make_blueprint.py` | balance, determinism, kinds and marks from the concept list, per-section difficulty, excluded concepts |
| `test_check_questions.py` | every Q rule, on a known-good paper with one fault planted per test |
| `test_review.py` | `extract_paper.py` (nothing leaks) and `compare_solutions.py` |
| `test_review_status.py`, `test_render_review.py` | the review loop's state and the report page |
| `test_render.py`, `test_latex.py` | markup, fonts, formulas and the built PDFs (their text needs pypdf) |
| `test_next_step.py`, `test_new_paper.py` | the workflow, step order, recording by hash, task folders |
| `test_approve_hook.py` | both hooks, each run as Claude Code runs it: a separate process given JSON on stdin |
| `test_skill_md.py` | the plugin's own files: every script `SKILL.md` names exists at its full path, agents are started by type, the manifests agree |

Not built yet: evals of the agents themselves (planted errors in a good paper, metrics from
`run.jsonl`, and a fixed set of papers rerun after each change).

## Where it runs

| Plugin part | Claude Code | Cowork | claude.ai chat |
|---|---|---|---|
| Skills, commands | yes | yes | yes |
| Agents, hooks | yes | yes | ignored |

claude.ai chat is not supported: without agents its "blind" solver would be the conversation that
wrote the key, and without hooks nothing is enforced. Cowork refuses a plugin with a top-level `bin/`,
so the scripts live inside the skill.

- **Claude Code, or Cowork on the teacher's computer:** hooks run beside the workspace, and a paper
  can span several sessions.
- **Cowork in the cloud** (Pro and Max plans, and Team or Enterprise with cloud sessions on): hooks run
  in a sandbox that ends with the task, so a paper is made from start to finish in one task, the
  concept list is approved again in each task, and the whole paper folder is delivered to the
  teacher's folder at the end as a record. The sandbox has Python with reportlab and matplotlib, and
  no TeX.

## Open questions

- The ICSE Physics syllabus includes spherical mirrors (with mirror-formula numericals) and
  electromagnets: check whether the book edition covers them (their concepts are included for now).
- Still to do: a finished example paper (approve the `icse9-physics-units1-4` blueprint, write its
  questions, review, render).
- Not checked yet: whether a cloud Cowork workspace survives between turns of the same task, and the
  hook probe in Claude Code on the teacher's own computer.
