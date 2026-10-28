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
review/reviewer-report.html + compare output ──user decides──▶ review/fixes.json
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

The reviewer writes its findings as JSON, then runs `skill/scripts/render_review.py` on that file, which
checks it and writes the HTML report beside it. Nobody writes or edits the HTML by hand.

```json
{
  "findings": [
    { "id": "R1", "severity": "error", "location": "Q18(b)",
      "problem": "The key gives 4 N but the force is 40 N.",
      "evidence": "F = ma = 8 × 5 = 40 N.",
      "suggestedFix": "Change the answer and the computed value to 40 N." }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | `R1`, `R2`, ... in order. |
| `severity` | `error`: the key is wrong, or the question cannot be answered or has more than one correct answer. `warning`: unclear wording, outside the syllabus or book level, tagged difficulty does not fit, a marking scheme that does not match the answer. `suggestion`: an improvement that does not affect correctness. |
| `location` | Where it is, e.g. `Q21(b)(ii)` (several: `Q6 and Q17(b)`). |
| `problem` | What is wrong. |
| `evidence` | A quotation or a calculation. |
| `suggestedFix` | A specific fix. |

- Plain text only (no markup); a line break is kept.
- Findings are ordered errors first, then warnings, then suggestions.
- If there is nothing to report, the file is `{ "findings": [] }`.
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

## `review/fixes.json` (written by Claude from the user's answer)

```json
{ "accepted": ["R1", "R5", "V1 Q7"], "rejected": ["R12"] }
```

The user's decision on the reviewer's findings and the comparison's mismatches: which to fix and
which to leave. `accepted` is an empty list if they want no changes. Only accepted fixes are applied to
`questions.json`; `next_step.py` then sends the paper back through the check and the blind solver.
