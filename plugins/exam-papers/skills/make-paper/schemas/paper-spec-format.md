# Paper spec format (`spec.json`)

The paper spec defines one exam paper: what it covers, its pattern of sections and marks, the
rules its content must follow, and what is produced. The user supplies it (Claude does not write
one from a chat description), and the skill's `scripts/validate_paper_spec.py` checks it before
anything else happens.

Template: `schemas/paper-spec.template.json` in the skill.

Fixed values (section types, difficulty levels, and so on) are defined once in
the skill's `scripts/spec_types.py`.

## Where the spec is used

| Step | Script or agent | Reads |
|---|---|---|
| Check the spec | `validate_paper_spec.py` | everything (rules S1–S20 below) |
| Make the task folder | `new_paper.py` | `exam.board`, `exam.class`, `exam.subject` (the folder name) |
| Plan the blueprint | `make_blueprint.py` | `exam.syllabusPack`, `exam.chapters`, `pattern`, the balance targets in `content` |
| Write the questions | writer agent | `pattern` and `content`, mainly `constants` and `diagrams` |
| Check the questions | `check_questions.py` | `exam`, `pattern`, `content` (rules Q1–Q16 in `question-format.md`) |
| Blind solve | `extract_paper.py`, blind solver | `exam.board`, `exam.class`, `exam.subject`, `content.constants` only |
| Review | reviewer agent | `pattern` and `content` |
| Make the PDFs | `render.py` | `exam`, `pattern`, `content.showChapterNames`, `content.constants`, `output` |

The "Used for" column in each table below says what a field changes.

## `exam`: what the paper covers

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `board` | text | e.g. `"ICSE"` | Task folder name; both PDF headings; must match the concept list's (Q8). |
| `class` | whole number | e.g. `9` | Task folder name; both PDF headings; must match the concept list's (Q8). |
| `subject` | text | e.g. `"Physics"` | Task folder name; both PDF headings and titles. |
| `book` | text, optional | e.g. `"Selina Concise Physics Part I"`; if given, it must match the concept list's | Only the Q8 match (checked when both name a book). Not printed. |
| `syllabusPack` | text | The syllabus pack the paper is made from: its folder name under `syllabi/` in the workspace, e.g. `"icse9-physics-selina"`. Its approved concept list decides what may be asked. | The blueprint reads `syllabi/<pack>/concepts.json` and refuses one that is not approved. |
| `chapters` | list of unit numbers | The syllabus units the paper may draw from, by the numbers the concept list gives them. (Every "chapter" in a spec is a syllabus unit; the PDFs print "Unit".) | The blueprint spreads questions over these; every question's `chapter` must be one (Q8); the answer key's heading lists them (`Units 1–4`). |

## `pattern`: sections and marks

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `totalMarks` | number | Marks a student can score (what they attempt, not what is offered). | The S7 cross-check; printed as "Maximum Marks" on both PDFs. |
| `durationMinutes` | whole number | Time allowed. | Printed as "Time allowed" on the paper (e.g. `1 hour 30 minutes`). |
| `sections` | list | In the order they appear on the paper. | The blueprint's question slots and the order of both PDFs. |
| `numbering` | `"continuous"` or `"per_section"` | Continuous: 1, 2, 3... across the paper. Per section: restart in each section. | The blueprint numbers questions this way; checked by Q2. |
| `smallestMarkUnit` | number | Smallest mark that can be awarded, e.g. `0.5`. Must divide 1 evenly. | The step the blueprint splits question marks into parts by; every mark is a multiple of it (Q6); with `markingScheme`, the key deducts this much for a missing or wrong unit. |

Each section:

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `id` | text | Section label, e.g. `"A"`. | Printed as "SECTION A" on both PDFs. |
| `type` | `"mcq"`, `"short_answer"` or `"long_answer"` | | The shape of each question (options, or parts); the key's layout (a table for MCQs, a worked answer for the rest). |
| `questionsOffered` | whole number | Questions printed in the section. | The blueprint's slot count; checked by Q3. |
| `questionsToAttempt` | whole number | Questions a student must answer. Equal to `questionsOffered` means no choice (a compulsory section). | The instruction printed for the section ("Answer all questions" or "Attempt any five questions out of seven"); which sections count as compulsory for `everyChapterInCompulsorySection`. |
| `marksPerQuestion` | number | Marks for each question. | The blueprint and Q3; printed beside each question. |
| `sectionTotal` | number | Marks a student can score in the section. Kept on purpose as a cross-check. | Only the S6 check. |
| `mcqOptions` | whole number | MCQ sections only: options per question. | Each MCQ has exactly this many options, labelled (a), (b)... (Q4). |
| `subParts` | `"none"`, `"allowed"` or `"required"` | Whether questions are split into parts (a), (b)... | How the blueprint splits each question's marks; checked by Q5. |
| `minSubParts`, `maxSubParts` | whole number, optional | Limits on the number of parts. | If left out, the minimum is 2 when `subParts` is `"required"` (S18 warns) and 1 when `"allowed"`; the maximum is `marksPerQuestion` ÷ `smallestMarkUnit`, which in practice means no limit. |
## `content`: rules for the questions

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `chapterWeightage` | object | `mode`: `"equal"`, or `"custom"` with `weights` (chapter number → percentage); `toleranceMarks`: allowed gap from each chapter's target. | The blueprint gives chapters to questions to stay within the tolerance; S19 warns if no split can; Q11 warns if the paper misses it. |
| `numericalTheorySplit` | object | `target`: `[numerical %, theory %]`; `tolerancePercent`. | The blueprint marks each part numerical or theory to meet the target; Q12 warns if the paper misses it. |
| `difficulty` | object | `target`: `{"easy": %, "medium": %, "hard": %}`; `tolerancePercent`. | The blueprint gives each part a level to meet the target; Q13 warns if the paper misses it. A level at **0%** is banned outright: any part at that level is an error (Q9), not a warning. |
| `everyChapterInCompulsorySection` | true/false | Every chapter has at least one question that every student must answer. | The blueprint places one compulsory question per chapter first; S14 checks there is room; Q10 is an error if it is missed. |
| `diagrams` | `"none"`, `"only_if_essential"` or `"allowed"` | | An instruction to the writer, which the reviewer checks. No script enforces it. |
| `showChapterNames` | true/false | Whether chapter names are printed next to questions. | If true, the paper prints "Unit N: title" above each question. The key always shows each question's unit and concepts. |
| `constants` | object | Values to use, e.g. `{"g": 9.8}`. | Printed in the paper's general instructions ("Take g = 9.8 m s⁻² unless stated otherwise"; only `g` gets a unit, other names print as given); the writer computes with them; passed to the blind solver and reviewer. `{}` prints nothing. |
| `avoidOverlappingConcepts` | true/false | Questions should not test the same concept twice. | If true, Q14 lists every concept used by more than one question, for review. The blueprint spreads concepts in either case. |

Custom weights are keyed by chapter number as a string, because JSON keys are always strings:

```json
"chapterWeightage": { "mode": "custom", "weights": { "1": 40, "2": 30, "3": 30 }, "toleranceMarks": 4 }
```

### How targets and tolerances work

Balance rules (chapters, numerical/theory, difficulty) are **targets with a tolerance**: question
marks come in fixed chunks, so exact splits are often impossible. The blueprint aims for each
target; the checker warns, but does not fail, when the paper ends up outside the tolerance.

Balance is measured on **marks offered**: every question printed, including the ones a student can
skip, because with choices every student attempts a different set. Each part counts its own marks under its own kind and difficulty. For the template (76 marks
offered: 15 + 21 + 40):

- **Chapters:** 5 chapters with `"equal"` means 15.2 marks each; `toleranceMarks: 5` allows 10.2 to
  20.2 per chapter.
- **Numerical/theory:** `[50, 50]` with `tolerancePercent: 5` allows 45–55% numerical, which is 34.2
  to 41.8 marks.
- **Difficulty:** easy 50, medium 50, hard 0 with `tolerancePercent: 10` allows 40–60% easy and
  40–60% medium, and no hard part at all.

The validator prints each chapter's target and an example split that meets the tolerance, so a
pattern that cannot balance shows up (S19) before any questions are written.

## `output`: what is produced

Two PDFs are always made: the question paper and the teacher's answer key, which always has every
answer.

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `header` | text or `null` | Text at the top of the paper; `null` for none. | Printed above the subject line of the question paper only (not the key). `\n` starts a new line, e.g. `"Half-Yearly Examination 2026\nGreenfield School"`. |
| `answerKey` | object | `include`: what the key adds to the answers, any of `"explanations"` and `"markingScheme"`; `[]` for answers only. | See below. |

What `answerKey.include` changes:

| Value | Effect on the answer key |
|---|---|
| `"explanations"` | Adds the explanation column to each MCQ section's answer table. |
| `"markingScheme"` | Prints the marking items under each answer, and the note on deducting `smallestMarkUnit` for a missing or wrong unit. |

## Examples

A section with no choice: make `questionsToAttempt` equal to `questionsOffered`. Its total is then
the whole section, and it counts as compulsory for `everyChapterInCompulsorySection`.

```json
{ "id": "A", "type": "mcq", "questionsOffered": 10, "questionsToAttempt": 10,
  "marksPerQuestion": 1, "sectionTotal": 10, "mcqOptions": 4, "subParts": "none" }
```

A section with choice, where every question has 2 to 4 parts: 6 printed, any 4 answered, 5 marks
each, so the section is worth 20 to a student and offers 30.

```json
{ "id": "B", "type": "long_answer", "questionsOffered": 6, "questionsToAttempt": 4,
  "marksPerQuestion": 5, "sectionTotal": 20, "subParts": "required",
  "minSubParts": 2, "maxSubParts": 4 }
```

An easier paper with no hard questions and more theory:

```json
"numericalTheorySplit": { "target": [30, 70], "tolerancePercent": 10 },
"difficulty": { "target": { "easy": 70, "medium": 30, "hard": 0 }, "tolerancePercent": 10 }
```

## Rules checked by `validate_paper_spec.py`

Every message starts with its rule number, e.g. `[S6] pattern.sections[B]: sectionTotal is 21 ...`.

**Errors** (the spec must be fixed before a blueprint is made):

- **S1.** Every field above is present (except those marked optional) with the right type, and
  every fixed value is one of the allowed options.
- **S2.** `chapters` is a non-empty list of positive chapter numbers with no duplicates.
- **S3.** `smallestMarkUnit` divides 1 evenly (1, 0.5, 0.25...).
- **S4.** Section ids are unique.
- **S5.** `questionsToAttempt` is not more than `questionsOffered`.
- **S6.** `sectionTotal` = `questionsToAttempt` × `marksPerQuestion`.
- **S7.** The section totals add up to `totalMarks`.
- **S8.** `marksPerQuestion` is a multiple of `smallestMarkUnit`.
- **S9.** An MCQ section has `subParts` `"none"` and at least 2 `mcqOptions`.
- **S10.** Sub-part limits are at least 2, the minimum is not above the maximum, they are not set
  when `subParts` is `"none"`, and a question's marks can be split into the minimum number of parts
  of at least `smallestMarkUnit` each.
- **S11.** Each percentage target adds up to 100; the difficulty target has exactly `easy`,
  `medium` and `hard`; the numerical/theory target has exactly two values; tolerances are 0–100.
- **S12.** Custom chapter weights cover every chapter in `exam.chapters`, no others, and add up to 100.
- **S14.** If `everyChapterInCompulsorySection` is true, there is a compulsory section and it has at
  least one question per chapter.
- **S15.** `header` is present, as text or `null`.
- **S20.** `exam.syllabusPack` is present and is a pack folder name: lower case letters and digits,
  words joined by hyphens.

**Warnings** (the spec is valid, but something looks off):

- **S16.** A field name is not recognised (usually a typo).
- **S17.** A field is set but ignored (`mcqOptions` on a non-MCQ section, `weights` with `"equal"`).
- **S18.** `subParts` is `"required"` without `minSubParts`; 2 is assumed.
- **S19.** Even the best possible chapter split is further from target than `toleranceMarks`.

The validator also reports, as information: marks offered versus attempted, each chapter's target,
and an example chapter split that meets the tolerance.
