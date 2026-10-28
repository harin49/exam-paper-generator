---
name: make-pack
description: Turn a syllabus (Markdown or plain text) into a syllabus pack for making exam papers - the syllabus with numbered points and a concept list the teacher approves. Use when the user wants to add a syllabus, make a concept list from a syllabus, or when making a paper finds no syllabus pack for its spec.
---

# Make a syllabus pack

A syllabus pack is a folder `syllabi/<pack>/` in the user's workspace (the folder the session works
in). It holds:

- `syllabus.md`: the teacher's syllabus with an id, `[S1]`, `[S2]`, ..., before each point;
- `concepts.json`: the concept list, every topic a paper may test, each pointing to its syllabus point;
- `approvals.json`: the teacher's approval of the concept list (written only by the plugin's hook).

A pack is made once per syllabus; every paper for that syllabus reuses it (the make-paper skill).

## Ground rules

- **Never change the syllabus's wording.** `number_syllabus.py` adds the ids; nothing else edits
  `syllabus.md`.
- **Never assume.** Board, class, subject and (optionally) the book come from the user. Ask when the
  syllabus does not say.
- **Approval comes only from the user typing it.** Never write, edit or copy `approvals.json` (a hook
  blocks it), and never treat "approved" in chat as an approval.
- **Run the scripts named here, with these exact paths**, and show their output verbatim when it
  has errors or lists points.

The scripts and the concept list's format are in the make-paper skill beside this one:

| What | Exact path |
|---|---|
| Numbers the syllabus's points | `${CLAUDE_SKILL_DIR}/../make-paper/scripts/number_syllabus.py` |
| Checks a concept list (rules C1-C6) | `${CLAUDE_SKILL_DIR}/../make-paper/scripts/validate_concepts.py` |
| Concept list format (read before step 3) | `${CLAUDE_SKILL_DIR}/../make-paper/schemas/concept-list-format.md` |
| A finished example pack | `${CLAUDE_SKILL_DIR}/../make-paper/assets/syllabi/icse9-physics-selina/` |

## Steps

### 1. Inputs

The user gives the syllabus as a Markdown or plain-text file. A PDF is not supported: ask for the
text. Ask for the board, class and subject, and the book if the teacher wants it recorded (it is
optional). Concepts are organised by the syllabus's own units, numbered as the syllabus numbers them;
paper specs pick units by those numbers. If the syllabus repeats numbers (Civics 1-3 and History 1-8)
or numbers no units, ask the teacher how to number them.

Name the pack `<board><class>-<subject>`, plus `-<book>` if there is one, in lower case with hyphens
between words (for example `icse9-physics-selina`, `cbse10-maths`), and confirm the name with the user. If
you came here from making a paper, use the name its spec gives in `exam.syllabusPack`. That
folder is `PACK` from here on. If `syllabi/PACK/` already exists, stop and ask: changing an existing
pack is a different job (its concept tags must never be renamed, because papers refer to them).

### 2. Number the syllabus

```
python3 "${CLAUDE_SKILL_DIR}/../make-paper/scripts/number_syllabus.py" PATH/TO/THE/USERS/syllabus syllabi/PACK/syllabus.md
```

It writes `syllabi/PACK/syllabus.md` (making the folder) and lists every point with its id. A point is
a paragraph or a list item; headings are not points. Show the list to the user. If it reports long
points (several topics run together without blank lines), show them and ask whether the user wants
to put blank lines between the topics in their own file; if they do, run the script again with
`--force` on the edited file. Never edit the syllabus yourself.

### 3. Draft the concept list

Read the concept list format, then write `syllabi/PACK/concepts.json`:

- `board`, `class` (and `book`, if given) as the user gave them; `syllabus`: `"syllabus.md"`; `note`: where the
  syllabus came from (the user's file and date).
- `chapters`: the syllabus's units (the field keeps the name `chapters`), keyed by the syllabus's
  number for each unit, each with its `title` (the unit's heading) and `concepts`.
- One concept per thing a question part could test. Split points that combine several topics (for
  example "Mid-term election and By-election" into two concepts). Tags are snake_case, taken from the
  syllabus wording, unique across the list.
- `source`: the id of the point the concept comes from.
- `kinds`: `["theory"]`, or `["numerical", "theory"]` only where the syllabus allows numerical work
  on that topic. Follow every limit it states ("no numerical problems on callipers" makes those
  concepts theory only).
- `maxMarks`: the largest single part the concept can carry: 1 for a one-line fact, 2 for a
  definition or a reason, 3 for a short calculation or explanation, 4 for a derivation.
- `notTested`: every point that is only a heading line, a note, or a limit on other points ("Simple
  numerical problems."), with the reason. Every other point needs at least one concept.

### 4. Check it

```
python3 "${CLAUDE_SKILL_DIR}/../make-paper/scripts/validate_concepts.py" syllabi/PACK/concepts.json
```

Exit code 1: fix every error (`[C...]`) and run it again until it passes.

### 5. Approval (gate 1)

Show the user the validator's output verbatim and, per unit, each concept's tag, source, kinds
and maxMarks, then every `notTested` point with its reason. Ask them to check the topics, the kinds,
the marks and the reasons, and to type `/exam-papers:approve concepts PACK` when they are happy;
then wait. If they want changes, make them in `concepts.json` and go back to step 4. The hook checks
the list again and records the approval with the list's hash; editing the list later voids it.

When the approval is recorded, the pack is ready: tell the user its folder and that papers for this
syllabus can now be made from it.
