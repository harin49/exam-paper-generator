# Concept list format (`concepts.json`)

A concept list names every topic a paper may test, for one board, class and book. It is kept in a
syllabus pack, `syllabi/<board><class>-<subject>-<book>/` in the teacher's workspace, beside the
syllabus it is drafted from, and is shared by every paper for that syllabus. Example:
`syllabi/icse9-physics-selina/concepts.json` (a sample copy ships with the skill, under
`assets/syllabi/`).

## How it is made and changed

1. **Drafted once from the syllabus** (`syllabus.md`), roughly one concept per syllabus point, with
   tags named from the syllabus wording. Claude drafts; it is never derived again at paper time.
2. **Checked** with the skill's `scripts/validate_concepts.py` (rules C1–C6 below): every syllabus section
   has a concept, every concept points to a real section, tags are unique.
3. **Approved by a teacher**, who checks topics, `kinds` and `maxMarks`, then sets `status` to
   `"approved"`. From then on the file is frozen: every paper reads it as it is.
4. **When the syllabus changes**, the old and new syllabus are compared and only the differences are
   proposed (concepts added or removed). Existing tags are never renamed, because older papers and
   blueprints refer to them.

Concepts are organised by **book chapter** (the numbers specs use). The syllabus may number its
sections differently; each concept's `source` points to its syllabus section.

## Fields

```json
{
  "board": "ICSE", "class": 9, "book": "Selina Concise Physics Part I",
  "syllabus": "syllabus.md", "syllabusYear": "2026-2027", "status": "draft",
  "chapters": {
    "1": { "title": "Measurements and Experimentation", "concepts": [
      { "tag": "vernier_callipers", "source": "1(ii)", "kinds": ["theory"], "maxMarks": 3 },
      { "tag": "pendulum_time_period_formula", "source": "1(ii)", "kinds": ["numerical", "theory"], "maxMarks": 3 }
    ] }
  }
}
```

| Field | Meaning |
|---|---|
| `board`, `class`, `book` | Must match the paper spec's `exam` (checked by rule Q8). |
| `syllabus` | The syllabus file, relative to this file. Its sections are marked `[1]`, `[1(i)]`, `[4(ii)]`... |
| `syllabusYear` | Optional: the syllabus year it was drafted from. |
| `status` | `"draft"` until a teacher approves it, then `"approved"`. |
| `note` | Optional free text. |
| `chapters` | Keyed by book chapter number: `title` and `concepts`. |
| `tag` | snake_case name, unique across the whole list. Used in blueprints and questions. |
| `source` | The syllabus section the concept comes from: a section with no sub-sections. |
| `kinds` | Which kinds of question the concept supports: `"numerical"`, `"theory"` or both. Encodes syllabus limits, e.g. "no numerical problems on callipers and screw gauge" makes `vernier_callipers` theory-only. |
| `maxMarks` | The largest single part (or sub-part) the concept can sensibly carry: 1 for a one-line fact, 2 for a definition or reason, 3 for a short calculation or explanation, 4 for a derivation. |

`make_blueprint.py` only pairs a part with a concept whose `kinds` include the part's kind and whose
`maxMarks` is at least the part's marks; `check_questions.py` checks the same (rule Q8).

## Rules checked by `validate_concepts.py`

Every message starts with its rule number, e.g. `[C6] syllabus [7(ii)]: has no concept`.

**Errors:**

- **C1.** Every field above is present with the right type; no unknown fields.
- **C2.** Tags are snake_case and unique across the whole list.
- **C3.** `kinds` is a non-empty list of allowed kinds, with no repeats.
- **C4.** `maxMarks` is a positive number.
- **C5.** Every `source` is a syllabus section that exists and has no sub-sections.
- **C6.** Every syllabus section without sub-sections has at least one concept (coverage).

**Warning:** C1 also warns while `status` is `"draft"`.

The validator also reports, as information, the number of concepts per chapter (and how many allow
numerical questions) and how many syllabus sections are covered.
