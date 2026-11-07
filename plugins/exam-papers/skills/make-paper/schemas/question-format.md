# Question format (`questions.json`)

`questions.json` holds every question in one paper, together with its answer key and marking
scheme. The writer subagent writes it from the blueprint; scripts check it; the PDF builder renders both the
question paper and the answer key from it. Nobody needs to write it by hand.

Example: `tests/test_data/questions.json` (the small test paper the unit tests use).

## File

```json
{
  "spec": "spec.json",
  "conceptList": "../../syllabi/icse9-physics-selina/concepts.json",
  "questions": [ ... ]
}
```

| Field | Meaning |
|---|---|
| `spec` | Path to the paper spec this paper was written for (relative to this file). |
| `conceptList` | Path to the fixed concept list that `concepts` tags must come from. |
| `questions` | All questions, in paper order. |

## Question

Every question has:

| Field | Type | Meaning |
|---|---|---|
| `number` | integer | Number printed on the paper. |
| `section` | string | Section id from the spec (`"A"`, `"B"`, ...). |
| `chapter` | integer | The one syllabus unit the question comes from (the concept list's unit number). Printed as "Unit N" only in the key, or next to the question when `showChapterNames` is on. |
| `concepts` | list of strings | Concept tags from the concept list (at least one). Used to detect overlap. |
| `marks` | number | Marks for the whole question. Must equal the section's `marksPerQuestion`. |

Then, depending on the section type:

**MCQ** (section type `mcq`) has no parts. It also has:

| Field | Type | Meaning |
|---|---|---|
| `kind` | `"numerical"` or `"theory"` | |
| `difficulty` | `"easy"`, `"medium"` or `"hard"` | |
| `text` | string | The question. |
| `options` | list of strings | Exactly as many as the spec's `mcqOptions`. Labelled (a), (b), ... when printed. |
| `correctOption` | string | `"a"`, `"b"`, ... |
| `explanation` | string | Why the answer is right and, where useful, why tempting wrong options are wrong. |
| `computed` | list | Required when `kind` is `"numerical"`. See below. |
| `concept` | string, optional | The concept this MCQ tests (one of `concepts`). Written by `make_blueprint.py`. |

**Short and long answer** questions have parts:

| Field | Type | Meaning |
|---|---|---|
| `stem` | string or `null` | Shared text printed before the parts (data, a scenario). |
| `parts` | list of parts | If the section's `subParts` is `"none"`, exactly one leaf part with label `""` (not printed). |
| `diagram` | object, optional | A diagram printed with the stem. |

## Part

A part is either a **leaf** (it is answered and marked) or a **group** (it holds sub-parts).
Groups go at most one level deep: a part's sub-parts must all be leaves.

**Leaf part:**

| Field | Type | Meaning |
|---|---|---|
| `label` | string | `"a"`, `"b"`... at the first level; `"i"`, `"ii"`... for sub-parts. |
| `text` | string | What the student is asked. |
| `marks` | number | Multiple of the spec's `smallestMarkUnit`. |
| `kind` | `"numerical"` or `"theory"` | One kind per leaf. If a part asks for both a calculation and a reason, split it into sub-parts. |
| `difficulty` | `"easy"`, `"medium"` or `"hard"` | |
| `answer` | string | The model answer as it appears in the answer key, with working. |
| `marking` | list of `{ "marks": number, "for": string }` | The marking scheme. The marks must add up to the part's `marks`. |
| `computed` | list | Required when `kind` is `"numerical"`. |
| `concept` | string, optional | The concept this part tests (one of the question's `concepts`). Written by `make_blueprint.py`. |
| `diagram` | object, optional | A diagram printed with this part on the question paper. |
| `answerDiagram` | object, optional | A diagram printed with this part in the answer key (e.g. an expected graph). |

**Group part:** `label`, `text` (the shared instruction, e.g. "Find:"), `marks` (must equal the
sum of its sub-parts) and `parts`. It has no `kind`, `difficulty`, `answer` or `marking`.

## `computed`

Every numerical answer is given as a formula; the checker calculates the value itself and compares
it with `value`. This stops a wrong number from reaching the answer key.

```json
"computed": [
  { "label": "pressure due to sea water", "expression": "15 * 1030 * 9.8", "value": 151410, "unit": "Pa" },
  { "label": "total pressure", "expression": "1.013e5 + 15 * 1030 * 9.8", "value": 252710, "unit": "Pa" }
]
```

- `expression`: plain arithmetic: numbers, `+ - * / **`, brackets, `pi` and `sqrt(...)`. Use the
  spec's constants as numbers (e.g. `9.8`, not `g`). It must be self-contained: no references to
  other answers.
- `value`: the result. `check_questions.py` recalculates the expression and requires `value` to agree
  with it to about 4 significant figures (relative difference under 0.01%), so 0.994 is accepted for
  0.993955... but 0.99 is not.
- `unit`: as printed, using the markup below; `""` for a pure number.
- `label`: optional, needed when a part has more than one value.
- `working`: optional; `true` for a step the marking scheme checks but the question does not ask for
  (e.g. u = 20 m s<sup>−1</sup> on the way to "find the retardation and the distance"). The blind
  solver is not expected to report working values (`compare_solutions.py` rule V4), though any it does
  report must still match. At least one value in each `computed` list must not be working.

## `diagram` and `answerDiagram`

```json
{ "description": "Velocity-time graph: (0,0) to (5,20) to (15,20) to (20,0)", "file": "vt_graph.png" }
```

`description` says exactly what the diagram must show; `file` is the image beside
`questions.json` (it may not exist yet when the question is first drafted). Diagrams are used only
where the spec allows them.

Claude draws each image (a small matplotlib script, saved as a PNG beside `questions.json`) when it
drafts the question. `render.py` only places the image: on the question paper for `diagram`, in the answer
key for `answerDiagram`. If the file is missing, `render.py` prints a labelled placeholder box showing the
`description` and ends its run with a warning that lists every missing image.

## Text markup

- Superscript: `cm<sup>2</sup>`, `m s<sup>−2</sup>`; subscript: `F<sub>2</sub>`.
- Bold and italic: `<b>...</b>`, `<i>...</i>` (e.g. "does <b>not</b> depend on").
- Line break inside an answer: `<br/>`.
- Use the minus sign `−` in units and negative values, `×` for multiplication and `÷` where
  division is written out.
- **Maths that needs layout** (fractions, roots, equations, indices on symbols, Greek letters) is
  written in LaTeX between dollar signs, in any printed field (text, stem, options, answer,
  explanation, marking items, diagram descriptions, units): `$\frac{v-u}{t}$` sits in the line, and
  `$$v^2 = u^2 + 2as$$` on its own is centred on a line of its own. A literal dollar sign is `\$`.
  Units and simple powers stay in the marks above (`m s<sup>−2</sup>`), so a value reads
  `$\frac{1}{2}$ m s<sup>−2</sup>` or `4.5 × 10<sup>3</sup> N`. In an MCQ option, a number may also
  be written `$4.5 \times 10^{3}$` (rule Q4 reads both).
- LaTeX is typeset by matplotlib's mathtext, which covers fractions, roots, powers and indices,
  Greek letters, integrals, sums and relations, but no environments (`\begin{...}`: matrices,
  aligned equations). Rule Q16 reports a formula it cannot typeset.
- No other markup. The PDF builder handles spacing and keeps values with their units.

## Rules the question checker will enforce

Rules are numbered Q1–Q16 (the paper spec's own rules are S1–S20, in `paper-spec-format.md`).
Every message from `check_questions.py` starts with its rule number, e.g. `[Q4] Q12: has 3 options
but the spec says 4`. If the spec itself is invalid, the checker reports `[S]` and skips the rules
that depend on it.

Hard rules (the paper cannot be built until they pass):

- **Q1.** Every field above is present with the right type; no unknown fields.
- **Q2.** Numbers run 1, 2, 3... in paper order (restarting in each section if the spec's numbering
  is `per_section`); each section's questions are together and in spec order; parts are labelled
  a, b, c... and sub-parts i, ii, iii... in order.
- **Q3.** Each section has exactly `questionsOffered` questions, each worth `marksPerQuestion`.
- **Q4.** MCQs: correct number of options, a valid `correctOption`, no parts. In a numerical MCQ the
  correct option starts with a number that shows a `computed` value, rounded at the option's own last
  digit ("1.33 Hz" shows 1.3333; "5 × 10<sup>4</sup> Pa" shows 50 000), and no other option shows one.
- **Q5.** Parts follow the spec's `subParts` rule (`none` / `allowed` / `required`, min and max).
- **Q6.** Leaf marks add up to the question's marks; group marks equal their sub-parts; every mark is a
   multiple of `smallestMarkUnit`; marking items add up to their leaf's marks.
- **Q7.** Every numerical leaf or MCQ has `computed`; every `expression` uses only the allowed
  arithmetic and recalculates to its `value` (to about 4 significant figures). Q7 cannot tell whether
  the formula fits the question: that is the blind solver's job.
- **Q8.** The concept list is for the spec's board and class (and book, when both name one), and lists each tag under one
  chapter only. Each question's `chapter` is one of the spec's chapters; its concept tags are all in
  the concept list, all belong to that chapter, and none is repeated. Where parts (or an MCQ) name their
  `concept`: either all of a question's parts do or none do; the question's `concepts` are exactly
  those named; and each part's kind is one of its concept's `kinds` and its marks are at most the
  concept's `maxMarks`.
- **Q9.** No question or part uses a difficulty level whose target in its section is 0% (e.g.
  `"hard"` in a section whose target is easy 50, medium 50, hard 0).
- **Q10.** If `everyChapterInCompulsorySection` is true, every chapter has at least one question in
  the compulsory section(s).

Soft rules (warnings: the paper still passes). Balance is measured on marks offered, counting
every leaf part's marks under its kind and difficulty:

- **Q11.** Each chapter's marks are within `toleranceMarks` of its target (equal share, or the
  custom weight). One warning lists every chapter outside the tolerance.
- **Q12.** The numerical percentage is within `tolerancePercent` of the target.
- **Q13.** In each section, each difficulty level's percentage of the section's marks offered is
  within the section's `tolerancePercent` of its target. One warning per section lists every level
  outside the tolerance.
- **Q14.** If `avoidOverlappingConcepts` is true, each concept tag used by more than one question is
  listed for review (possible overlap).

`check_questions.py` also reports, as information, the marks offered by chapter, the
numerical/theory split and each section's difficulty mix, each against its target, and the
whole paper's difficulty mix.

## Blueprint (`blueprint.json`)

The blueprint is the slot-by-slot plan that `questions.json` is written from. It is made by a
script (`make_blueprint.py`) from the paper spec and the concept list, approved by the user, and kept beside the spec and
questions as the record of what was approved. Approval is not a field in the file: the user types
`/exam-papers:approve blueprint`, and the plugin's hook records the file's hash in `approvals.json`
beside it. Questions are only written from an approved blueprint, and any edit to the file voids
its approval. It has the same shape as `questions.json` but only the
structural fields: no wording, answers, marking or computed values.

```json
{
  "spec": "spec.json",
  "conceptList": "../../syllabi/icse9-physics-selina/concepts.json",
  "questions": [
    { "number": 1, "section": "A", "chapter": 1, "marks": 1,
      "concepts": ["vernier_least_count"], "kind": "numerical", "difficulty": "easy",
      "correctOption": "c" },
    { "number": 21, "section": "B", "chapter": 4, "marks": 3,
      "concepts": ["pascals_law", "hydraulic_press"],
      "parts": [
        { "label": "a", "marks": 1, "kind": "theory", "difficulty": "easy" },
        { "label": "b", "marks": 2, "parts": [
          { "label": "i",  "marks": 1, "kind": "numerical", "difficulty": "medium" },
          { "label": "ii", "marks": 1, "kind": "numerical", "difficulty": "easy" } ] }
      ] }
  ]
}
```

| Field | Meaning |
|---|---|
| question fields | `number`, `section`, `chapter`, `marks`, `concepts`; MCQs also `kind`, `difficulty`, `concept` and `correctOption` (dealt by `make_blueprint.py` so the letters are used evenly). |
| part fields | Leaf: `label`, `marks`, `kind`, `difficulty`, `concept`. Group: `label`, `marks`, `parts`. |

All balance rules (chapters, numerical/theory, difficulty, compulsory coverage) can be checked on the
blueprint alone, before any question is written.

Additional hard rule for the question checker:

- **Q15.** `questions.json` must match its blueprint exactly on every structural field: the same questions
  in the same order with the same number, section, chapter, marks and concepts (and, for MCQs, the
  same `correctOption`), and the same parts with the same labels, marks, kind, difficulty and concept. Claude adds wording; it never changes a slot.
- **Q16.** Every LaTeX formula in a printed field is closed (`$...$`, `$$...$$`; a literal dollar is
  `\$`) and can be typeset by mathtext. The message quotes the formula and the reason (for example
  `Unknown symbol: \begin`).
