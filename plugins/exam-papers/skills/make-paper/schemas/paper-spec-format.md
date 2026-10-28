# Paper spec format (`spec.json`)

The paper spec defines one exam paper: what it covers, its pattern of sections and marks, the
rules its content must follow, and what is produced. Claude writes it from the user's answers to
the clarifying questions (or the user supplies one), and the skill's `scripts/validate_paper_spec.py`
checks it before anything else happens.

Template: `schemas/paper-spec.template.json` in the skill.

Fixed values (section types, difficulty levels, and so on) are defined once in
the skill's `scripts/spec_types.py`.

## `exam`: what the paper covers

| Field | Type | Meaning |
|---|---|---|
| `board` | text | e.g. `"ICSE"` |
| `class` | whole number | e.g. `9` |
| `subject` | text | e.g. `"Physics"` |
| `book` | text | e.g. `"Selina Concise Physics Part I"` |
| `syllabusPack` | text | The syllabus pack the paper is made from: its folder name under `syllabi/` in the workspace, e.g. `"icse9-physics-selina"`. Its approved concept list decides what may be asked. |
| `chapters` | list of chapter numbers | The chapters the paper may draw from. |

## `pattern`: sections and marks

| Field | Type | Meaning |
|---|---|---|
| `totalMarks` | number | Marks a student can score (what they attempt, not what is offered). |
| `durationMinutes` | whole number | Time allowed. |
| `sections` | list | In the order they appear on the paper. |
| `numbering` | `"continuous"` or `"per_section"` | Continuous: 1, 2, 3... across the paper. Per section: restart in each section. |
| `smallestMarkUnit` | number | Smallest mark that can be awarded, e.g. `0.5`. Must divide 1 evenly. |

Each section:

| Field | Type | Meaning |
|---|---|---|
| `id` | text | Section label, e.g. `"A"`. |
| `type` | `"mcq"`, `"short_answer"` or `"long_answer"` | |
| `questionsOffered` | whole number | Questions printed in the section. |
| `questionsToAttempt` | whole number | Questions a student must answer. Equal to `questionsOffered` means no choice (a compulsory section). |
| `marksPerQuestion` | number | Marks for each question. |
| `sectionTotal` | number | Marks a student can score in the section. Kept on purpose as a cross-check. |
| `mcqOptions` | whole number | MCQ sections only: options per question. |
| `subParts` | `"none"`, `"allowed"` or `"required"` | Whether questions are split into parts (a), (b)... |
| `minSubParts`, `maxSubParts` | whole number, optional | Limits on the number of parts. |
| `singleChapterPerQuestion` | true/false, optional | Every question in the section comes from one chapter. |

## `content`: rules for the questions

| Field | Type | Meaning |
|---|---|---|
| `chapterWeightage` | object | `mode`: `"equal"`, or `"custom"` with `weights` (chapter number → percentage); `toleranceMarks`: allowed gap from each chapter's target. |
| `numericalTheorySplit` | object | `target`: `[numerical %, theory %]`; `tolerancePercent`. |
| `difficulty` | object | `target`: `{"easy": %, "medium": %, "hard": %}`; `tolerancePercent`. |
| `measureOn` | `"offered"` | Balance is measured on all marks printed, because with choices every student attempts a different set. |
| `everyChapterInCompulsorySection` | true/false | Every chapter has at least one question that every student must answer. |
| `diagrams` | `"none"`, `"only_if_essential"` or `"allowed"` | |
| `showChapterNames` | true/false | Whether chapter names are printed next to questions. |
| `constants` | object | Values to use, e.g. `{"g": 9.8}`. |
| `avoidOverlappingConcepts` | true/false | Questions should not test the same concept twice. |

Balance rules (chapters, numerical/theory, difficulty) are **targets with a tolerance**: question
marks come in fixed chunks, so exact splits are often impossible.

## `output`: what is produced

| Field | Type | Meaning |
|---|---|---|
| `header` | text or `null` | Text at the top of the paper; `null` for none. |
| `paperFormat` | `"pdf"` | |
| `answerKey` | object | `format` (`"pdf"`), `audience` (`"teacher"` or `"student"`), `include` (any of `"answers"`, `"explanations"`, `"markingScheme"`). |

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
- **S13.** `measureOn` is `"offered"`.
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
