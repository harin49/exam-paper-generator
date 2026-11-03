# Concept list format (`concepts.json`)

A concept list names every topic a paper may test, for one board, class and syllabus (and,
optionally, book). It is kept in a syllabus pack, `syllabi/<board><class>-<subject>[-<book>]/` in
the teacher's workspace, beside the
syllabus it is drafted from, and is shared by every paper for that syllabus. Example:
`syllabi/icse9-physics-selina/concepts.json` (a sample copy ships with the skill, under
`assets/syllabi/`).

## How it is made and changed

The plugin's make-pack skill (`/exam-papers:make-pack`) walks through steps 1-4.

1. **The syllabus is numbered.** `scripts/number_syllabus.py` copies the teacher's syllabus into
   the pack as `syllabus.md`, inserting a unique id, `[S1]`, `[S2]`, ..., before each point (each
   paragraph and each list item; headings are not points). Nothing else is changed, and the teacher's
   own file is left as it is. The ids carry no meaning; they only let concepts point at the text.
2. **Drafted once from the syllabus** (`syllabus.md`), roughly one concept per syllabus point, with
   tags named from the syllabus wording. Claude drafts; it is never derived again at paper time.
   A point that is only a heading line, a note or a limit on other points ("Simple numerical
   problems.") goes in `notTested` with the reason, instead of getting a concept.
3. **Checked** with the skill's `scripts/validate_concepts.py` (rules C1–C6 below): every syllabus point
   has a concept or a reason in `notTested`, every concept points to a real point, tags are unique.
4. **Approved by a teacher**, who checks topics, `kinds`, `maxMarks` and the `notTested` reasons,
   then types `/exam-papers:approve concepts`. A hook runs `validate_concepts.py` (it refuses a list
   with errors) and records the approval with the list's SHA-256 hash in `approvals.json` beside it.
   From then on the file is frozen: `make_blueprint.py` refuses a list that is not approved as it is
   now, so editing it voids the approval until the teacher approves it again.
5. **When the syllabus changes**, the old and new syllabus are compared and only the differences are
   proposed (concepts added or removed). Existing tags are never renamed, because older papers and
   blueprints refer to them.

Concepts are organised by the **syllabus's own units**, under the field name `chapters` (the field
keeps its name; a "chapter" in these files is a unit of the syllabus). Each unit is keyed by the
syllabus's own number for it and titled with its heading, so the ICSE Physics syllabus's unit 4
"Fluids" is one unit, though the book splits it over two chapters. Where a syllabus repeats numbers
(for example Civics 1-3 and History 1-8), the teacher decides how the units are numbered. Specs pick
units by these numbers. The book is optional. Each concept's `source` is the id of the syllabus point
it comes from.

## Fields

```json
{
  "board": "ICSE", "class": 9, "book": "Selina Concise Physics Part I",
  "syllabus": "syllabus.md", "syllabusYear": "2026-2027",
  "notTested": { "S17": "Heading only: the topic's content is S18." },
  "chapters": {
    "1": { "title": "Measurements and Experimentation", "concepts": [
      { "tag": "vernier_callipers", "source": "S2", "kinds": ["theory"], "maxMarks": 3 },
      { "tag": "pendulum_time_period_formula", "source": "S3", "kinds": ["numerical", "theory"], "maxMarks": 3 }
    ] }
  }
}
```

| Field | Meaning |
|---|---|
| `board`, `class`, `book` | Must match the paper spec's `exam` (checked by rule Q8). `book` is optional; it is compared only when both name one. |
| `syllabus` | The numbered syllabus file, relative to this file. Its points carry ids `[S1]`, `[S2]`, ... (from `number_syllabus.py`). |
| `syllabusYear` | Optional: the syllabus year it was drafted from. |
| `note` | Optional free text (where the syllabus came from, anything changed in it). |
| `notTested` | Optional: syllabus points with no concept, each with the reason (`{"S17": "Heading only..."}`). Shown to the teacher at approval. |
| `chapters` | The syllabus's units, keyed by the syllabus's number for each: `title` (the unit's heading) and `concepts`. |
| `tag` | snake_case name, unique across the whole list. Used in blueprints and questions. |
| `source` | The id of the syllabus point the concept comes from, e.g. `"S3"`. |
| `kinds` | Which kinds of question the concept supports: `"numerical"`, `"theory"` or both. Encodes syllabus limits, e.g. "no numerical problems on callipers and screw gauge" makes `vernier_callipers` theory-only. |
| `maxMarks` | The largest single part (or sub-part) the concept can sensibly carry: 1 for a one-line fact, 2 for a definition or reason, 3 for a short calculation or explanation, 4 for a derivation. |

`make_blueprint.py` only pairs a part with a concept whose `kinds` include the part's kind and whose
`maxMarks` is at least the part's marks; `check_questions.py` checks the same (rule Q8).

## Rules checked by `validate_concepts.py`

Every message starts with its rule number, e.g. `[C6] syllabus [S45]: has no concept`.

**Errors:**

- **C1.** `board`, `class`, `syllabus` and `chapters` are present; every field has the right
  type; no unknown fields.
- **C2.** Tags are snake_case and unique across the whole list.
- **C3.** `kinds` is a non-empty list of allowed kinds, with no repeats.
- **C4.** `maxMarks` is a positive number.
- **C5.** The syllabus's point ids run `S1`, `S2`, ... once each, in order; every `source` and every
  `notTested` id is one of them.
- **C6.** Every syllabus point has at least one concept, or is in `notTested` with a reason
  (coverage). A point in `notTested` that also has concepts is a warning.

The validator also reports, as information, the number of concepts per chapter (and how many allow
numerical questions) and how many syllabus points are covered, and which are not tested and why.
