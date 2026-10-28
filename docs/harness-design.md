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
| Agents | Independent roles: blind solver, reviewer |
| Hooks | Enforcement: block actions that break the rules |

The user starts a paper by invoking the skill with a spec and a syllabus; nothing else to set up.

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

The teacher approves by typing a command such as `/exam:approve blueprint`. A `UserPromptSubmit` hook
(code that runs when the user sends a message) records the approval in the task's `approvals.json`:
which gate, which file, the file's SHA-256 hash and the time. A `PreToolUse` hook blocks Claude from
writing `approvals.json`. A gate counts as passed only while the approved file still has the recorded
hash, so editing an approved file voids its approval.

```mermaid
sequenceDiagram
    actor T as Teacher
    participant H as UserPromptSubmit hook
    participant A as approvals.json
    participant C as Claude
    participant P as PreToolUse hook
    T->>H: /exam:approve blueprint
    H->>A: gate, file, sha256, time
    C->>P: write approvals.json?
    P-->>C: blocked
    C->>A: read: blueprint approved and hash matches?
```

*Why:* trust comes from where an action originates. Claude cannot send user messages, so it cannot
create an approval; the hash ties the approval to the exact content the teacher saw.

*Limit:* this guards against mistakes, not a determined adversary. A `PreToolUse` hook can match
`Write`/`Edit` on the file exactly, but a Bash command can only be pattern-matched, so a creative
command could still slip through.

### D7. Four approval gates

Each gate is passed only by a typed command (D6).

| Gate | When | What the teacher approves |
|---|---|---|
| Concept list | Once per book, after `validate_concepts.py` passes | The concepts drafted from the syllabus |
| Blueprint | Every paper, before any wording is written | Chapter, concept, marks, kind and difficulty of every part |
| Finding decisions | After each review round with warnings or suggestions, and for any finding still open after round 3 | Accept or reject each warning and suggestion (errors are fixed without asking, D1); settle each disagreement (D3) |
| Final paper | After review ends, before the PDFs are rendered | The reviewed questions and key, and the list of automatic fixes (D2) |

The spec is not a gate: the teacher writes it, and `validate_paper_spec.py` checks it.

*Why:* each gate sits where a teacher's judgement is needed and a mistake would be costly to undo
later. The final gate is new: today nothing asks the teacher to sign off the finished paper.

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

### D11. Chapters are the syllabus's own units

A concept list is organised by the syllabus's units or sections, and a spec selects units. The book
becomes optional information.

*Why:* syllabi arrive without a book's contents (D9), so units are the only structure every syllabus
has. Consequence: the existing ICSE Physics list is organised by Selina book chapters (syllabus unit 4
"Fluids" is book chapters 4 and 5) and has to be moved to syllabus units.

### D12. Syllabus packs and papers live in the teacher's workspace

The plugin holds only code, prompts and formats. Everything a teacher makes lives in their workspace
(the project folder in Claude Code, the attached folder in Cowork):

- `syllabi/<pack>/`: `syllabus.md`, `concepts.json`, approvals;
- `papers/<task>/`: spec, blueprint, questions, `review/`, `approvals.json`, PDFs.

*Why:* an installed plugin is a cache that should not be written to, and Cowork can only write to
attached folders. The teacher owns and can see everything.

### D13. A writer subagent drafts and revises the questions

Main Claude only orchestrates: it runs the steps, talks with the teacher and passes work between roles.
A writer subagent drafts `questions.json` from the approved blueprint and revises it for accepted
findings.

*Why:* clear roles and smaller contexts, and each role's tools and file access can be set separately
(the writer never needs the solver's answers; the solver never sees the key).

### D14. State is a hash ledger plus a run log

- `state.json` in each task folder records every finished step with the SHA-256 hashes of its inputs
  and outputs. A step is done only while those hashes still match the files; changing an input makes
  that step and every step after it due again.
- `run.log` is an append-only record of every step, script result, agent call, approval and automatic
  fix, with times.

*Why:* file timestamps break on a copy, a `git checkout` or any re-save (re-printing the review findings
once sent a finished paper back to an earlier step). Hashes depend only on content. The log gives the
teacher an audit trail (D2) and gives the evals their data (D17).

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
- **Run metrics:** from `run.log`: check failures, solver mismatches, findings by severity, rounds
  used, automatic fixes, and findings the teacher rejected.
- **Golden papers:** a fixed set of syllabi and specs rerun after every change to the prompts or
  scripts, with their metrics compared to the previous run.

*Why:* unit tests check the scripts, not the agents. Planted errors show whether review works; run
metrics and golden papers show whether a change made things better or worse.

### Architecture

```mermaid
flowchart LR
    subgraph Plugin["Plugin (installed, read-only)"]
        SK[Skill: playbook, scripts, formats]
        AG[Agents: writer, blind solver, reviewer]
        CM[Commands: /exam:approve, /exam:decide]
        HK[Hooks: record approvals, block leaks]
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

Not documented, so to be tested before relying on them in Cowork:

- whether a hook fires inside a subagent and can block its file reads;
- whether a subagent's `tools` allowlist is applied;
- whether `reportlab` and `matplotlib` are available in Cowork's VM;
- whether `UserPromptSubmit` hooks fire for typed plugin commands (D6).

## Open questions

None at present. Questions answered so far: who drives the loop (D4, D5), first-version scope (D8),
syllabus input (D9), approvals (D6), gates (D7), state (D14), question kinds (D15), formats (D16),
evals (D17).
