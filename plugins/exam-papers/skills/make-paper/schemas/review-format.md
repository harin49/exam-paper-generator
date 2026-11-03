# Review formats

The review step has two independent checks. Both start from `questions.json`, and neither edits it.

1. **Blind solver.** A subagent that sees only the paper as a student would, with no answers. A
   script prepares what it sees, and a script compares what it writes with the key.
2. **Reviewer.** A subagent that sees everything (key, spec, concept list, syllabus) and looks for
   problems a script cannot find.

Files go in a `review/` folder beside `questions.json`.

```
questions.json ──extract_paper.py──▶ review/solver-input.json ──blind solver──▶ review/solver-answers.json
                                                                                        │
questions.json ─────────────────────────────compare_solutions.py◀───────────────────────┘
                                                      │
                                                      ▼
                                          review/compare-output.txt
questions.json + spec + concept list + syllabus + compare output ──reviewer──▶ review/reviewer-report.json ──render_review.py──▶ review/reviewer-report.html
review_status.py ──user decides──▶ review/decisions.json; errors and accepted findings ──writer──▶ review/writer-response.json ──▶ next round
```

## `review/solver-input.json` (written by `extract_paper.py`)

```json
{
  "paper": { "board": "ICSE", "class": 9, "subject": "Physics", "constants": { "g": 9.8 } },
  "questions": [
    { "number": 1, "section": "A", "marks": 1, "type": "mcq",
      "text": "The S.I. unit of linear momentum is:", "options": ["kg m s^(−2)", "N s^(−1)", "..."] },
    { "number": 21, "section": "B", "marks": 3, "type": "parts", "stem": null,
      "parts": [
        { "label": "a", "text": "State Pascal's law.", "marks": 1, "id": "a" },
        { "label": "b", "text": "... Find:", "marks": 2, "parts": [
          { "label": "i",  "text": "the pressure ...", "marks": 1, "id": "b(i)" },
          { "label": "ii", "text": "the force ...",    "marks": 1, "id": "b(ii)" } ] } ] }
  ]
}
```

- Only what the printed paper shows is kept. Left out: `answer`, `marking`, `explanation`,
  `correctOption`, `computed`, `kind`, `difficulty`, `chapter`, `concepts`, `concept`,
  `answerDiagram`. The script refuses to write the file if any of those appears in it.
- A `diagram` is kept as `{ "description": ... }` only: the solver cannot see the image, so the
  description must give it everything the picture shows.
- Markup becomes plain text: `m s<sup>−2</sup>` is `m s^(−2)`, `F<sub>2</sub>` is `F_2`.
- Each answerable part has an `id`: its label, with sub-parts as `b(ii)`; `""` for a single
  unlabelled part. Groups (a part that only holds sub-parts) have no `id`.

## `review/solver-answers.json` (written by the blind solver)

```json
{
  "answers": [
    { "number": 1, "choice": "c" },
    { "number": 21, "id": "a", "answer": "Pressure applied to an enclosed liquid is transmitted ..." },
    { "number": 21, "id": "b(i)", "answer": "P = F/A = 20 / 5e-4 = 4e4 Pa",
      "values": [ { "value": 40000, "unit": "Pa" } ] },
    { "number": 12, "choice": "b", "problem": "Options (b) and (c) are both correct." }
  ]
}
```

| Field | Meaning |
|---|---|
| `number` | The question number. Required. |
| `id` | The part id from `solver-input.json`. Omit for an MCQ. |
| `choice` | MCQ only: the option letter. |
| `answer` | Other parts: the answer in words, with brief working. |
| `values` | Parts that ask for a calculation: every final numerical result the part asks for, as `{ "value": number, "unit": text }`, in the unit stated. Leave out for theory parts. |
| `problem` | Optional. Say so here if the question is ambiguous, has missing or inconsistent data, or has no single correct answer. |

Every question and every part must have exactly one answer.

## Rules checked by `compare_solutions.py`

Every message starts with its rule number, e.g. `[V1] Q5: the solver chose (d) but the key says (b)`.

| Rule | Meaning |
|---|---|
| **V1** | An MCQ: the solver chose a different option from the key. |
| **V2** | A numerical part: a value the solver gave matches no `computed` value in the key (agreement means within 1%). |
| **V3** | Same, but the values differ only by a power of ten (probably a unit difference) or only in sign (probably a direction convention). |
| **V4** | A numerical part: the solver gave no values, or gave none for a `computed` value the question asks for (values marked `"working": true` are not required). |
| **V5** | A question or part is unanswered, an id is unknown or repeated, or the file is malformed. |
| **V6** | (warning) The solver reported a `problem` with a question. |

The key's `computed` list may hold intermediate values the question does not ask for, so the check
runs from the solver's values to the key, not the other way round.

**Theory parts cannot be compared by a script.** `compare_solutions.py` lists each one under INFO with the
key's answer and the solver's answer side by side, for the reviewer to judge.

Exit codes: 0 no mismatches (V6 problems alone do not change it), 1 mismatches found (V1-V5: show them
to the user; change nothing until they have seen them), 2 a file could not be read.

In the workflow it runs with `--out TASK/review/compare-output.txt`, which saves the same report to that
file. The report's last line is `Result: NO MISMATCHES` or `Result: N MISMATCH(ES)`.

## `review/reviewer-report.json` and `review/reviewer-report.html` (written by the reviewer)

The reviewer writes its findings as JSON, then runs the skill's `scripts/render_review.py` on that file, which
checks it and writes the HTML report beside it. Nobody writes or edits the HTML by hand.

```json
{
  "findings": [
    { "id": "R1", "severity": "error", "status": "open", "location": "Q18(b)",
      "problem": "The key gives 4 N but the force is 40 N.",
      "evidence": "F = ma = 8 × 5 = 40 N.",
      "suggestedFix": "Change the answer and the computed value to 40 N." }
  ],
  "dismissed": [
    { "mismatch": "[V1] Q5: the solver chose (d) but the key says (b)",
      "reason": "The key is right; the solver took g as 9.8 m/s² instead of the spec's 10." }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | `R1`, `R2`, ... in order. A later round keeps every earlier finding with its ID and numbers new ones after them. |
| `severity` | `error`: the key is wrong, or the question cannot be answered or has more than one correct answer. `warning`: unclear wording, outside the syllabus or book level, tagged difficulty does not fit, a marking scheme that does not match the answer. `suggestion`: an improvement that does not affect correctness. |
| `status` | `open` or `resolved`. Round 1: all `open`. Later rounds: the reviewer marks each earlier finding. |
| `location` | Where it is, e.g. `Q21(b)(ii)` (several: `Q6 and Q17(b)`). |
| `problem` | What is wrong. |
| `evidence` | A quotation or a calculation. |
| `suggestedFix` | A specific fix. |
| `note` | Optional. Why a finding was resolved or is still open, or why its severity changed (required when it changed). |
| `dismissed` | Optional. The solver's mismatches (`[V1]`-`[V6]` lines from the comparison) that the reviewer judged not to be problems in the paper, each with `mismatch` (the line) and `reason`. Every mismatch is either quoted in a finding's evidence or listed here. |

- Plain text only (no markup); a line break is kept.
- Findings are in ID order. `render_review.py` displays open findings first, by severity.
- If there is nothing to report, the file is `{ "findings": [] }`.
- The writer never sees the comparison: findings are how it learns of a real mismatch.
- `render_review.py` refuses a file that breaks these rules (exit code 1) and writes nothing. It also
  prints the findings as plain text, which is what Claude shows the user verbatim:

```
# Review of questions.json
Findings: 3 (1 error, 1 warning, 1 suggestion)

## R1  Q18(b)  error
Problem: ...
Evidence: ...
Suggested fix: ...
```

## `review/rounds.json` and `review/rounds/N/` (written by `review_status.py --close-round`)

```json
{ "rounds": [
  { "round": 1, "key": "...", "report": "<sha256>", "questions": "<sha256>", "time": "..." }
] }
```

One entry per closed review round; `review/rounds/N/` keeps that round's `questions.json` and
`reviewer-report.json` as they were, and the `writer-response.json` of the revision that led to it
(`writerResponse` is its hash, or null when no new revision did). `review_status.py TASK --fixes`
builds the final approval's list of every change from these. A round is identified by its report, questions and the writer's
latest responses together (`key`). Closing refuses a report that drops an earlier finding or changes a
severity without a `note`. `review_status.py TASK --changes` lists what changed in `questions.json`
since the last closed round; the reviewer gets it from round 2 on.

## `review/decisions.json` (written only by the plugin's hook, when the user types `/exam-papers:decide`)

```json
{ "decisions": [
  { "round": 1, "report": "<sha256 of reviewer-report.json>", "accepted": ["R2"], "rejected": ["R5"],
    "undo": [], "time": "2026-10-28T10:05:00+00:00", "command": "/exam-papers:decide accept R2 reject R5" }
] }
```

The user's decisions on open warnings and suggestions, and on disputes (findings the writer
disagreed with that the reviewer kept open, and findings still open after round 3), one entry per typed command, never rewritten. The hook refuses a decision that leaves a
listed finding undecided, accepts a finding that is not listed, or rejects one that is neither listed
nor an open error (the user may overrule the reviewer on an error) nor a fix the writer made. Rejecting
a resolved finding the writer fixed undoes the fix: the hook lists it in `undo`, and the writer
restores the text in the next revision. A hook also stops Claude and the
subagents from writing the file. Only `R` IDs: a solver mismatch reaches the user
as a finding (or as a dismissal they can question). A rejected finding stays closed; an accepted one
is fixed by the writer like an error. From round 3 on, an `accepted` ID in the entry for the current
round gives the writer one more round for it.

`review_status.py TASK` reads the report, the rounds and the decisions and says what is next:
`decide` (gate 3), `revise` (the writer, without asking: open errors and accepted findings before
round 3), or `done`.

## `review/writer-response.json` (written by the writer)

```json
{ "responses": [
  { "id": "R1", "action": "fixed", "location": "Q18(b)",
    "change": "Answer and computed value changed from 4 N to 40 N; marking item 2 updated." },
  { "id": "R4", "action": "disagree", "location": "Q7(a)",
    "reason": "The data is sufficient: the mass is given in the stem (2 kg)." }
] }
```

The writer's answer to each finding it was asked to address, once per ID: `fixed` with the `change`
it made (specific enough to undo), `disagree` with its `reason` and evidence, leaving the paper as
it was, or `reverted` when the user undid an earlier fix and the writer restored the text. Claude
shows it to the user after each revision. Closing a round saves the response that led to it in
`review/rounds/N/writer-response.json`, so every revision is kept for the final approval.
