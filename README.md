# Exam Paper Generator

A Claude plugin, **exam-papers**, that makes exam question papers and teacher answer keys (two PDFs)
from a syllabus and a paper spec. Scripts plan and check the structure, Claude writes the wording, and
a blind solver and an independent reviewer check the paper before the teacher approves it. How the
harness works is in [`docs/harness-design.md`](docs/harness-design.md).

## Install

**Claude Code:**

```
/plugin marketplace add harin49/exam-paper-generator
/plugin install exam-papers@exam-paper-generator
```

Claude Code runs the plugin's scripts with your own Python 3, so install the two packages they need
(reportlab for the PDFs, matplotlib for formulas and diagrams):

```bash
pip3 install "reportlab>=4.0" "matplotlib>=3.8"
```

**Claude desktop app or Cowork:**

1. Open **Customize > Plugins** and choose **Add marketplace**.
2. Enter `harin49/exam-paper-generator`. If the repo is private, connect your GitHub account when asked.
3. Install **exam-papers** from that marketplace.

Updating the plugin, trying edits from a clone and running the tests are in
[`docs/development.md`](docs/development.md).

## Get started

This example makes an ICSE Class 9 Physics paper on units 1–4 with the sample syllabus pack that
ships with the plugin. Type each `/exam-papers:...` command in the chat yourself: Claude cannot
approve or decide for you.

1. **Make a workspace folder** for your papers (not this repo) and start Claude Code in it. In Cowork,
   choose this folder for the task instead.

   ```bash
   mkdir -p ~/exam-papers && cd ~/exam-papers
   ```

   ```bash
   claude
   ```

2. **Add a paper spec.** Save [`examples/icse9-physics-units1-4/spec.json`](examples/icse9-physics-units1-4/spec.json)
   as `~/exam-papers/spec.json`. It sets the units, sections, marks and difficulty, and names the
   syllabus pack (`exam.syllabusPack`). For your own paper, start from
   [`paper-spec.template.json`](plugins/exam-papers/skills/make-paper/schemas/paper-spec.template.json);
   every field is explained in
   [`paper-spec-format.md`](plugins/exam-papers/skills/make-paper/schemas/paper-spec-format.md).

3. **Start the paper.**

   ```
   /exam-papers:make-paper spec.json
   ```

   Claude makes the paper's folder, `papers/icse-9-physics-<date>/`, and checks the spec. The first
   time, it offers to copy the sample pack into `syllabi/icse9-physics-selina/`: say yes.

4. **Approve the concept list** (once per syllabus pack), after reading the concepts Claude shows:

   ```
   /exam-papers:approve concepts
   ```

5. **Approve the blueprint**, the plan of every question's unit, concept, marks, kind and difficulty:

   ```
   /exam-papers:approve blueprint
   ```

6. **Decide the review findings.** Claude writes the questions, a blind solver and a reviewer check
   them, and errors are fixed without asking. Accept or reject the warnings and suggestions Claude
   lists, by their ids:

   ```
   /exam-papers:decide accept R2 R4 reject R5
   ```

7. **Approve the final paper.** Claude then builds the question paper and the answer key as PDFs in
   `papers/icse-9-physics-<date>/`.

   ```
   /exam-papers:approve paper
   ```

**Your own syllabus:** give Claude the syllabus file (Markdown or text) and type
`/exam-papers:make-pack`. It numbers the syllabus's points, drafts a concept list and asks you to
approve it with `/exam-papers:approve concepts`. Name that pack in your spec's `exam.syllabusPack`.

## Workflow

The steps from syllabus to PDFs, with the four points where you approve or decide, are drawn in the
[architecture diagram](docs/architecture.md); the review loop has [its own](docs/review-loop.md).

## Layout

```
.claude-plugin/marketplace.json     # makes this repo a marketplace listing the plugin
plugins/exam-papers/                # the plugin: the only part that is installed
  .claude-plugin/plugin.json
  agents/                           # writer.md (drafts and revises), blind-solver.md, reviewer.md
  commands/                         # approve.md: /exam-papers:approve concepts|blueprint|paper;
                                    # decide.md: /exam-papers:decide accept … reject … (typed by the teacher)
  hooks/                            # hooks.json; approve.py (records typed approvals and decisions);
                                    # guard.py (nobody writes approvals.json or decisions.json;
                                    # what the solver and the writer may see)
  skills/make-pack/SKILL.md         # turns a syllabus into a syllabus pack (uses make-paper's scripts)
  skills/make-paper/
    SKILL.md                        # main workflow
    workflow.json                   # the steps in order: who does each, approval points, when done
    schemas/                        # spec (S-rules), questions + blueprint (Q-rules), concept list
                                    # (C-rules), review files (V-rules); spec template
    scripts/                        # run: validate_paper_spec, validate_concepts, make_blueprint,
                                    # check_questions, render, new_paper, extract_paper,
                                    # compare_solutions, next_step, render_review, review_status,
                                    # number_syllabus; libraries: paper (labels, part walk, names),
                                    # report (Report, value checks), task_files (JSON, hashes,
                                    # run log), approvals, spec_types, latex
    assets/syllabi/icse9-physics-selina/   # sample pack: syllabus.md, concepts.json (approve once copied)
docs/harness-design.md              # the harness: scripts, state, hooks, agents, gates, tests
docs/architecture.md                # diagrams: plugin and workspace, syllabus to PDFs
docs/review-loop.md                 # diagram: how a paper is reviewed and revised
docs/development.md                 # updating, trying edits from a clone, tests, releases
examples/icse9-physics-units1-4/    # example paper: spec + draft blueprint
tests/                              # unit tests; tests/test_data/ holds their fixed data
requirements.txt, requirements-dev.txt
```
