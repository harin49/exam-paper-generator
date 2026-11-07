#!/usr/bin/env python3
"""Check a questions.json file against its paper spec and blueprint.

Usage:
    python3 check_questions.py QUESTIONS.json [--blueprint BLUEPRINT.json] [--json]

The spec and concept list are the files named in QUESTIONS.json's "spec" and "conceptList"
fields (relative to its folder). By default
the blueprint is the blueprint.json in the same folder as QUESTIONS.json. It must be approved: the
approvals.json beside it (see approvals.py) has the teacher's approval of it as it is now.

Exit codes:
    0  passed (warnings may still be printed)
    1  errors found: the paper must not be built
    2  a file could not be read or is not valid JSON

Rules implemented so far (see schemas/question-format.md in this skill):
    Q1   fields present, correct types and values, no unknown fields
    Q2   question numbers, section order and part labels in sequence
    Q3   questions per section and marks per question match the spec
    Q4   MCQ options and correct option; a numerical MCQ's correct option shows its computed value
    Q5   number of parts follows the section's subParts rule
    Q6   marks add up (parts, sub-parts, marking items) in multiples of the smallest mark unit
    Q7   every numerical answer has a computed formula that recalculates to its stored value
    Q8   concept tags come from the concept list and the question's own chapter
    Q9   no difficulty level the spec's target excludes (0%), e.g. hard
    Q10  every chapter appears in the compulsory section(s), if the spec requires it
    Q11  (warning) chapter balance within the spec's tolerance
    Q12  (warning) numerical/theory split within the spec's tolerance
    Q13  (warning) difficulty mix within the spec's tolerance
    Q14  (warning) questions sharing a concept tag, listed for review
Balance (Q11-Q13) is measured on marks offered: with choices, every student attempts a different set.
    Q15  questions.json matches its approved blueprint on every structural field
    Q16  every LaTeX formula ($...$, $$...$$) is closed and can be typeset
Every message starts with its rule number, e.g. "[Q4] Q12: ...".
"""
import ast
import json
import math
import operator
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import latex  # noqa: E402
from approvals import is_approved  # noqa: E402
from spec_types import Difficulty, Kind, Numbering, SectionType, SubParts  # noqa: E402
from paper import LETTERS, ROMAN, where  # noqa: E402
from report import Report, fmt, frac, is_int, is_num, keys_ok  # noqa: E402
from task_files import load_json  # noqa: E402
from validate_paper_spec import validate as validate_spec  # noqa: E402

TOP_KEYS = {"spec", "conceptList", "questions"}
Q_COMMON = {"number", "section", "chapter", "concepts", "marks"}
MCQ_REQUIRED = Q_COMMON | {"kind", "difficulty", "text", "options", "correctOption", "explanation"}
MCQ_KEYS = MCQ_REQUIRED | {"computed", "diagram", "concept"}
PARTED_REQUIRED = Q_COMMON | {"stem", "parts"}
PARTED_KEYS = PARTED_REQUIRED | {"diagram"}
LEAF_REQUIRED = {"label", "text", "marks", "kind", "difficulty", "answer", "marking"}
LEAF_KEYS = LEAF_REQUIRED | {"computed", "diagram", "answerDiagram", "concept"}
GROUP_KEYS = {"label", "text", "marks", "parts"}
COMPUTED_KEYS = {"label", "expression", "value", "unit", "working"}
DIAGRAM_KEYS = {"description", "file"}


def show(v):
    return json.dumps(v, ensure_ascii=False)


def nonempty_str(x):
    return isinstance(x, str) and bool(x.strip())


# ---------------- Q1: fields, types and values ----------------
def field(r, obj, key, loc, check, desc):
    if key in obj and not check(obj[key]):
        r.error(loc, f"{key} must be {desc} (got {show(obj[key])})", "Q1")


def check_computed(r, comp, loc):
    if not (isinstance(comp, list) and comp):
        r.error(loc, "computed must be a non-empty list", "Q1")
        return
    for i, c in enumerate(comp, 1):
        cl = f"{loc} computed #{i}"
        if not isinstance(c, dict):
            r.error(cl, "must be an object", "Q1")
            continue
        keys_ok(r, c, COMPUTED_KEYS, {"expression", "value", "unit"}, cl, "Q1")
        field(r, c, "expression", cl, nonempty_str, "a non-empty formula")
        field(r, c, "value", cl, is_num, "a number")
        field(r, c, "unit", cl, lambda x: isinstance(x, str), "text ('' for no unit)")
        field(r, c, "label", cl, nonempty_str, "non-empty text")
        field(r, c, "working", cl, lambda x: isinstance(x, bool), "true or false")
        if len(comp) > 1 and "label" not in c:
            r.error(cl, "needs a label when there is more than one computed value", "Q1")
    if all(isinstance(c, dict) and c.get("working") is True for c in comp):
        r.error(loc, "every computed value is marked working: at least one must be an answer the "
                     "question asks for", "Q1")


def check_diagram(r, obj, key, loc):
    if key not in obj:
        return
    d = obj[key]
    if not isinstance(d, dict):
        r.error(loc, f"{key} must be an object", "Q1")
        return
    keys_ok(r, d, DIAGRAM_KEYS, {"description"}, f"{loc} {key}", "Q1")
    field(r, d, "description", f"{loc} {key}", nonempty_str, "non-empty text")
    field(r, d, "file", f"{loc} {key}", nonempty_str, "a file name")


def check_kind_difficulty(r, obj, loc):
    field(r, obj, "kind", loc, lambda x: x in Kind.values(), f"one of {sorted(Kind.values())}")
    field(r, obj, "difficulty", loc, lambda x: x in Difficulty.values(),
          f"one of {sorted(Difficulty.values())}")


def check_part_fields(r, p, qnum, labels, depth):
    loc = where(qnum, labels + (p.get("label"),))
    if "parts" in p:  # group
        if depth > 1:
            r.error(loc, "sub-parts cannot have their own parts (one level of nesting only)", "Q1")
        keys_ok(r, p, GROUP_KEYS, GROUP_KEYS, loc, "Q1")
        field(r, p, "label", loc, lambda x: isinstance(x, str), "text")
        field(r, p, "text", loc, nonempty_str, "non-empty text")
        field(r, p, "marks", loc, lambda x: is_num(x) and x > 0, "a positive number")
        if not (isinstance(p["parts"], list) and p["parts"]):
            r.error(loc, "parts must be a non-empty list", "Q1")
            return
        for sp in p["parts"]:
            if isinstance(sp, dict):
                check_part_fields(r, sp, qnum, labels + (p.get("label"),), depth + 1)
            else:
                r.error(loc, "each sub-part must be an object", "Q1")
        return
    keys_ok(r, p, LEAF_KEYS, LEAF_REQUIRED, loc, "Q1")
    field(r, p, "label", loc, lambda x: isinstance(x, str), "text")
    field(r, p, "text", loc, nonempty_str, "non-empty text")
    field(r, p, "marks", loc, lambda x: is_num(x) and x > 0, "a positive number")
    check_kind_difficulty(r, p, loc)
    field(r, p, "answer", loc, nonempty_str, "non-empty text")
    field(r, p, "concept", loc, nonempty_str, "a concept tag")
    if "marking" in p:
        m = p["marking"]
        if not (isinstance(m, list) and m):
            r.error(loc, "marking must be a non-empty list", "Q1")
        else:
            for i, item in enumerate(m, 1):
                ml = f"{loc} marking #{i}"
                if not isinstance(item, dict):
                    r.error(ml, "must be an object", "Q1")
                    continue
                keys_ok(r, item, {"marks", "for"}, {"marks", "for"}, ml, "Q1")
                field(r, item, "marks", ml, lambda x: is_num(x) and x > 0, "a positive number")
                field(r, item, "for", ml, nonempty_str, "non-empty text")
    if "computed" in p:
        check_computed(r, p["computed"], loc)
    check_diagram(r, p, "diagram", loc)
    check_diagram(r, p, "answerDiagram", loc)


def check_fields(r, qdoc, sections):
    """Q1 for the whole file. Returns the list of well-formed question objects."""
    keys_ok(r, qdoc, TOP_KEYS, TOP_KEYS, "file", "Q1")
    field(r, qdoc, "spec", "file", nonempty_str, "a file path")
    field(r, qdoc, "conceptList", "file", nonempty_str, "a file path")
    qs = qdoc.get("questions")
    if not (isinstance(qs, list) and qs):
        r.error("file", "questions must be a non-empty list", "Q1")
        return []
    good = []
    for i, q in enumerate(qs, 1):
        if not isinstance(q, dict):
            r.error(f"question #{i}", "must be an object", "Q1")
            continue
        loc = where(q.get("number", f"#{i}"))
        sec = sections.get(q.get("section"))
        is_mcq = sec["type"] == SectionType.MCQ if sec else ("options" in q)
        if is_mcq:
            keys_ok(r, q, MCQ_KEYS, MCQ_REQUIRED, loc, "Q1")
        else:
            keys_ok(r, q, PARTED_KEYS, PARTED_REQUIRED, loc, "Q1")
        field(r, q, "number", loc, lambda x: is_int(x) and x > 0, "a positive whole number")
        field(r, q, "section", loc, nonempty_str, "a section id")
        field(r, q, "chapter", loc, lambda x: is_int(x) and x > 0, "a chapter number")
        field(r, q, "concepts", loc, lambda x: isinstance(x, list) and x and all(nonempty_str(c) for c in x),
              "a non-empty list of concept tags")
        field(r, q, "marks", loc, lambda x: is_num(x) and x > 0, "a positive number")
        if is_mcq:
            check_kind_difficulty(r, q, loc)
            field(r, q, "text", loc, nonempty_str, "non-empty text")
            field(r, q, "options", loc, lambda x: isinstance(x, list) and x and all(nonempty_str(o) for o in x),
                  "a non-empty list of options")
            field(r, q, "correctOption", loc, lambda x: isinstance(x, str) and len(x) == 1 and x in LETTERS,
                  "a single letter")
            field(r, q, "explanation", loc, nonempty_str, "non-empty text")
            field(r, q, "concept", loc, nonempty_str, "a concept tag")
            if "computed" in q:
                check_computed(r, q["computed"], loc)
        else:
            field(r, q, "stem", loc, lambda x: x is None or nonempty_str(x), "text or null")
            parts = q.get("parts")
            if "parts" in q and not (isinstance(parts, list) and parts):
                r.error(loc, "parts must be a non-empty list", "Q1")
            elif isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict):
                        check_part_fields(r, p, q.get("number"), (), 1)
                    else:
                        r.error(loc, "each part must be an object", "Q1")
        check_diagram(r, q, "diagram", loc)
        good.append(q)
    return good


# ---------------- Q2: numbering, section order, part labels ----------------
def check_sequence(r, qs, spec_sections, numbering):
    order = list(spec_sections)
    expected, prev_sec = 0, None
    seen = set()
    for q in qs:
        sid, num = q.get("section"), q.get("number")
        if sid != prev_sec:
            if sid in seen:
                r.error(where(num), f"section {sid} appears again after section {prev_sec}; "
                                    "keep each section's questions together", "Q2")
            elif prev_sec in order and sid in order and order.index(sid) < order.index(prev_sec):
                r.error(where(num), f"section {sid} comes after section {prev_sec}, but the spec "
                                    f"orders sections {', '.join(order)}", "Q2")
            seen.add(sid)
            if numbering == Numbering.PER_SECTION:
                expected = 0
            prev_sec = sid
        expected += 1
        if num != expected:
            r.error(where(num), f"is numbered {show(num)} but should be {expected}", "Q2")


def check_labels(r, qs, spec_sections):
    for q in qs:
        parts = q.get("parts")
        if not isinstance(parts, list):
            continue
        sec = spec_sections.get(q.get("section"))
        if sec and sec["subParts"] == SubParts.NONE:
            continue  # Q5 covers the single unlabelled part
        for i, p in enumerate(parts):
            if not isinstance(p, dict):
                continue
            want = LETTERS[i] if i < len(LETTERS) else None
            if p.get("label") != want:
                r.error(where(q.get("number"), (p.get("label"),)),
                        f"part {i + 1} should be labelled {show(want)}", "Q2")
            for j, sp in enumerate(p.get("parts") or []):
                if not isinstance(sp, dict):
                    continue
                want_s = ROMAN[j] if j < len(ROMAN) else None
                if sp.get("label") != want_s:
                    r.error(where(q.get("number"), (p.get("label"), sp.get("label"))),
                            f"sub-part {j + 1} should be labelled {show(want_s)}", "Q2")


# ---------------- Q3: questions per section, marks per question ----------------
def check_section_counts(r, qs, spec_sections):
    counts = {sid: 0 for sid in spec_sections}
    for q in qs:
        sid = q.get("section")
        if sid not in spec_sections:
            r.error(where(q.get("number")), f"section {show(sid)} is not in the spec "
                                            f"({', '.join(spec_sections)})", "Q3")
            continue
        counts[sid] += 1
        want = spec_sections[sid]["marksPerQuestion"]
        if is_num(q.get("marks")) and q["marks"] != want:
            r.error(where(q.get("number")), f"is worth {q['marks']} marks but section {sid} questions "
                                            f"are worth {want}", "Q3")
    for sid, n in counts.items():
        want = spec_sections[sid]["questionsOffered"]
        if n != want:
            r.error(f"section {sid}", f"has {n} questions but the spec offers {want}", "Q3")


# ---------------- Q4: MCQs ----------------
def check_mcqs(r, qs, spec_sections):
    for q in qs:
        sec = spec_sections.get(q.get("section"))
        if not sec or sec["type"] != SectionType.MCQ:
            continue
        loc = where(q.get("number"))
        if "parts" in q:
            r.error(loc, "an MCQ must not have parts", "Q4")
        opts = q.get("options")
        if not isinstance(opts, list):
            continue
        n = sec.get("mcqOptions")
        if n and len(opts) != n:
            r.error(loc, f"has {len(opts)} options but the spec says {n}", "Q4")
        stripped = [o.strip().lower() for o in opts if isinstance(o, str)]
        if len(set(stripped)) != len(stripped):
            r.error(loc, "has two identical options", "Q4")
        c = q.get("correctOption")
        valid = LETTERS[:len(opts)]
        if isinstance(c, str) and c not in valid:
            r.error(loc, f"correctOption is {show(c)} but the options run {valid[0]}–{valid[-1]}", "Q4")
        elif isinstance(c, str) and q.get("kind") == Kind.NUMERICAL:
            check_option_values(r, q, opts, c, loc)


# A number at the start of an option: 1.25, −0.5, 50,000 or 5 × 10<sup>4</sup>.
OPTION_NUMBER = re.compile(r"\s*([−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?)"
                           r"(?:\s*×\s*10\s*<sup>\s*([−-]?\d+)\s*</sup>)?")


def option_number(text):
    """(value, step) for the number an option starts with, or None. step is the place value of the
    option's last digit (0.01 for "1.25", 1000 for "5 × 10<sup>3</sup>")."""
    text = latex.number_marks(text) if isinstance(text, str) else text      # "$4.5 \\times 10^{3}$"
    m = OPTION_NUMBER.match(text) if isinstance(text, str) else None
    if not m:
        return None
    exp = int(m.group(3).replace("−", "-")) if m.group(3) else 0
    mantissa = float(m.group(1).replace("−", "-").replace(",", ""))
    decimals = len(m.group(2) or "")
    return mantissa * 10 ** exp, 10 ** (exp - decimals)


def check_option_values(r, q, opts, correct, loc):
    """Q4 for a numerical MCQ: the correct option shows a computed value, and no other option does."""
    comp = q.get("computed")
    values = [c["value"] for c in comp if isinstance(c, dict) and is_num(c.get("value"))
              and c.get("working") is not True] if isinstance(comp, list) else []
    if not values:
        return  # Q1 or Q7 reports it

    def shows_value(opt):
        n = option_number(opt)
        # The option matches a value that rounds to it at the option's own last digit.
        return n is not None and any(abs(n[0] - v) <= n[1] / 2 * (1 + 1e-9) for v in values)

    i = LETTERS.index(correct)
    computed = ", ".join(fmt(v) for v in values)
    if option_number(opts[i]) is None:
        r.error(loc, f"is numerical, but the correct option ({correct}) does not start with a number "
                     f"to check against the computed value {computed}", "Q4")
    elif not shows_value(opts[i]):
        r.error(loc, f"the correct option ({correct}) shows {show(opts[i])} but the computed value is "
                     f"{computed}", "Q4")
    for j, opt in enumerate(opts):
        if j != i and isinstance(opt, str) and shows_value(opt):
            r.error(loc, f"option ({LETTERS[j]}) also shows the computed value {computed}: two options "
                         "would be correct", "Q4")


# ---------------- Q16: LaTeX maths ----------------
PRINTED = {"text", "stem", "answer", "explanation", "for", "description", "unit"}


def printed_text(node, loc):
    """(location, text) for every printed text field in a question or part, options included."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in PRINTED and isinstance(v, str):
                yield f"{loc} {k}", v
            elif k == "options" and isinstance(v, list):
                for j, o in enumerate(v):
                    if isinstance(o, str):
                        yield f"{loc} option ({LETTERS[j] if j < len(LETTERS) else j})", o
            elif k == "parts" and isinstance(v, list):
                for p in v:
                    if isinstance(p, dict):
                        yield from printed_text(p, f"{loc}({p.get('label')})" if p.get("label") else loc)
            elif isinstance(v, (dict, list)) and k not in ("parts", "options"):
                yield from printed_text(v, loc)
    elif isinstance(node, list):
        for x in node:
            yield from printed_text(x, loc)


def check_math(r, qs):
    for q in qs:
        if not isinstance(q, dict):
            continue
        for loc, text in printed_text(q, f"Q{q.get('number')}"):
            if "$" not in text:
                continue
            for problem in latex.problems(text):
                r.error(loc, problem, "Q16")


# ---------------- Q5: number of parts ----------------
def check_part_counts(r, qs, spec_sections):
    for q in qs:
        sec = spec_sections.get(q.get("section"))
        parts = q.get("parts")
        if not sec or sec["type"] == SectionType.MCQ or not isinstance(parts, list):
            continue
        loc, n, rule = where(q.get("number")), len(parts), sec["subParts"]
        if rule == SubParts.NONE:
            p = parts[0] if parts and isinstance(parts[0], dict) else {}
            if n != 1 or p.get("label") != "" or "parts" in p:
                r.error(loc, f"section {sec['id']} has no sub-parts, so the question must be a single "
                             "part with label \"\" and no sub-parts", "Q5")
            continue
        mn = sec.get("minSubParts", 2 if rule == SubParts.REQUIRED else 1)
        mx = sec.get("maxSubParts")
        if n < mn:
            r.error(loc, f"has {n} part(s) but section {sec['id']} needs at least {mn}", "Q5")
        if mx is not None and n > mx:
            r.error(loc, f"has {n} parts but section {sec['id']} allows at most {mx}", "Q5")


# ---------------- Q6: marks add up ----------------
def check_unit(r, value, smu, loc, what):
    if smu and is_num(value) and value > 0 and (frac(value) / frac(smu)).denominator != 1:
        r.error(loc, f"{what} {fmt(value)} is not a multiple of the smallest mark unit ({fmt(smu)})", "Q6")


def check_leaf_marks(r, p, loc, smu):
    check_unit(r, p.get("marks"), smu, loc, "marks")
    items = p.get("marking")
    if not (isinstance(items, list) and items and all(isinstance(m, dict) for m in items)):
        return
    if not all(is_num(m.get("marks")) for m in items):
        return  # Q1 reports the bad values
    for i, m in enumerate(items, 1):
        check_unit(r, m["marks"], smu, f"{loc} marking #{i}", "marks")
    total = sum(frac(m["marks"]) for m in items)
    if is_num(p.get("marks")) and total != frac(p["marks"]):
        r.error(loc, f"marking adds up to {fmt(float(total))} but the part is worth {fmt(p['marks'])}", "Q6")


def sum_parts(parts):
    """Sum of marks over a list of parts, or None if any mark is missing or not a number."""
    if not all(isinstance(p, dict) and is_num(p.get("marks")) for p in parts):
        return None
    return sum(frac(p["marks"]) for p in parts)


def check_marks(r, qs, smu):
    for q in qs:
        num = q.get("number")
        parts = q.get("parts")
        if not isinstance(parts, list) or not parts:
            continue  # MCQ: its marks are checked by Q3
        total = sum_parts(parts)
        if total is not None and is_num(q.get("marks")) and total != frac(q["marks"]):
            r.error(where(num), f"parts add up to {fmt(float(total))} marks but the question is worth "
                                f"{fmt(q['marks'])}", "Q6")
        for p in parts:
            if not isinstance(p, dict):
                continue
            loc = where(num, (p.get("label"),))
            sub = p.get("parts")
            if isinstance(sub, list) and sub:
                check_unit(r, p.get("marks"), smu, loc, "marks")
                st = sum_parts(sub)
                if st is not None and is_num(p.get("marks")) and st != frac(p["marks"]):
                    r.error(loc, f"sub-parts add up to {fmt(float(st))} marks but the part is worth "
                                 f"{fmt(p['marks'])}", "Q6")
                for sp in sub:
                    if isinstance(sp, dict) and "parts" not in sp:
                        check_leaf_marks(r, sp, where(num, (p.get("label"), sp.get("label"))), smu)
            elif "parts" not in p:
                check_leaf_marks(r, p, loc, smu)


# ---------------- Q7: computed answers ----------------
RELATIVE_TOLERANCE = 1e-4   # value must agree with the formula to about 4 significant figures
MAX_EXPONENT = 100
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_NAMES = {"pi": math.pi}
_FUNCS = {"sqrt": math.sqrt}


class ExpressionError(ValueError):
    pass


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and is_num(node.value):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ExpressionError(f"the power {fmt(right)} is too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _NAMES:
            return _NAMES[node.id]
        raise ExpressionError(f"uses '{node.id}'; write constants as numbers (e.g. 9.8, not g)")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if len(node.args) != 1 or node.keywords:
            raise ExpressionError(f"{node.func.id}() takes exactly one value")
        return _FUNCS[node.func.id](_eval(node.args[0]))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        raise ExpressionError(f"uses {node.func.id}(); only sqrt() is allowed")
    raise ExpressionError("contains something other than numbers, + - * / **, brackets, pi and sqrt()")


def evaluate(expression):
    """Evaluate a formula from a computed entry. Raises ExpressionError with a readable reason."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        raise ExpressionError("is not valid arithmetic") from None
    try:
        result = _eval(tree)
    except ExpressionError:
        raise
    except ZeroDivisionError:
        raise ExpressionError("cannot be calculated: division by zero") from None
    except (OverflowError, ValueError) as e:
        raise ExpressionError(f"cannot be calculated: {e}") from None
    if not math.isfinite(result):
        raise ExpressionError("does not give a finite number")
    return result


def check_computed_values(r, obj, loc):
    """Q7 for one numerical leaf or MCQ."""
    comp = obj.get("computed")
    if obj.get("kind") != "numerical":
        return
    if not comp:
        r.error(loc, "is numerical but has no computed answers", "Q7")
        return
    if not isinstance(comp, list):
        return  # Q1 reports it
    for i, c in enumerate(comp, 1):
        if not isinstance(c, dict) or not isinstance(c.get("expression"), str):
            continue  # Q1 reports it
        cl = f"{loc} computed #{i}" + (f" ({c['label']})" if isinstance(c.get("label"), str) else "")
        try:
            got = evaluate(c["expression"])
        except ExpressionError as e:
            r.error(cl, f"expression {show(c['expression'])} {e}", "Q7")
            continue
        want = c.get("value")
        if not is_num(want):
            continue  # Q1 reports it
        if not math.isclose(got, want, rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-12):
            r.error(cl, f"expression gives {got:.6g} but value is {want:.6g}", "Q7")


def leaves_with_location(q):
    num = q.get("number")
    for p in q.get("parts") or []:
        if not isinstance(p, dict):
            continue
        if isinstance(p.get("parts"), list):
            for sp in p["parts"]:
                if isinstance(sp, dict) and "parts" not in sp:
                    yield sp, where(num, (p.get("label"), sp.get("label")))
        elif "parts" not in p:
            yield p, where(num, (p.get("label"),))


def check_answers(r, qs):
    for q in qs:
        if isinstance(q.get("parts"), list):
            for leaf, loc in leaves_with_location(q):
                check_computed_values(r, leaf, loc)
        else:
            check_computed_values(r, q, where(q.get("number")))


# ---------------- Q8: concept tags ----------------
def read_concept_list(r, concepts, spec):
    """Validate the concept list. Returns {tag: {"chapter", "kinds", "maxMarks"}} or None if unusable.

    Accepts the current format (each concept an object with tag, source, kinds, maxMarks) and the
    older one (each concept a plain tag string, with no kinds or maxMarks).
    """
    if not isinstance(concepts, dict) or not isinstance(concepts.get("chapters"), dict):
        r.error("conceptList", "must be an object with a 'chapters' object", "Q8")
        return None
    if spec is not None:
        exam = spec.get("exam", {})
        for k in ("board", "class", "book"):
            if k in concepts and (k in exam or k != "book") and concepts[k] != exam.get(k):
                r.error("conceptList", f"is for {k} {show(concepts[k])} but the spec says "
                                       f"{show(exam.get(k))}", "Q8")
    tags = {}
    for ch, entry in concepts["chapters"].items():
        if not (ch.isdigit() and isinstance(entry, dict) and isinstance(entry.get("concepts"), list)):
            r.error("conceptList", f"chapter {show(ch)} must have a 'concepts' list", "Q8")
            continue
        for c in entry["concepts"]:
            if isinstance(c, dict):
                t, info = c.get("tag"), {"chapter": int(ch), "kinds": c.get("kinds"), "maxMarks": c.get("maxMarks")}
            else:
                t, info = c, {"chapter": int(ch), "kinds": None, "maxMarks": None}
            if not isinstance(t, str):
                r.error("conceptList", f"chapter {ch} has a concept without a tag", "Q8")
                continue
            if t in tags:
                r.error("conceptList", f"tag '{t}' is listed under chapters {tags[t]['chapter']} and {ch}", "Q8")
            tags[t] = info
    return tags


def check_part_concept(r, obj, loc, q_concepts, tags):
    """Q8 for a leaf part or MCQ that names its concept."""
    t = obj.get("concept")
    if not isinstance(t, str):
        return
    if isinstance(q_concepts, list) and t not in q_concepts:
        r.error(loc, f"concept '{t}' is not in the question's concepts", "Q8")
    info = (tags or {}).get(t)
    if not info:
        return  # an unknown tag is reported through the question's concepts
    kinds, max_marks = info.get("kinds"), info.get("maxMarks")
    if isinstance(kinds, list) and obj.get("kind") not in kinds:
        r.error(loc, f"is {obj.get('kind')}, but concept '{t}' only allows {', '.join(kinds)}", "Q8")
    if is_num(max_marks) and is_num(obj.get("marks")) and obj["marks"] > max_marks:
        r.error(loc, f"is worth {fmt(obj['marks'])} marks, but concept '{t}' allows at most "
                     f"{fmt(max_marks)} per part", "Q8")


def check_concepts(r, qs, tags, chapters):
    for q in qs:
        loc, ch, cs = where(q.get("number")), q.get("chapter"), q.get("concepts")
        if chapters and is_int(ch) and ch not in chapters:
            r.error(loc, f"chapter {ch} is not one of the spec's chapters {sorted(chapters)}", "Q8")
        if not isinstance(cs, list):
            continue
        if len(set(cs)) != len(cs):
            r.error(loc, "lists the same concept tag twice", "Q8")
        for t in (cs if tags is not None else []):
            if t not in tags:
                r.error(loc, f"concept '{t}' is not in the concept list", "Q8")
            elif is_int(ch) and tags[t]["chapter"] != ch:
                r.error(loc, f"concept '{t}' belongs to chapter {tags[t]['chapter']}, but the question is "
                             f"from chapter {ch}", "Q8")
        items = list(leaves_with_location(q)) if isinstance(q.get("parts"), list) else [(q, loc)]
        named = [obj.get("concept") for obj, _ in items if "concept" in obj]
        if named:
            if len(named) != len(items):
                r.error(loc, "some parts name their concept and some don't; either all or none should", "Q8")
            elif set(named) != set(cs):
                r.error(loc, "the question's concepts should be exactly the concepts its parts name", "Q8")
        for obj, ploc in items:
            check_part_concept(r, obj, ploc, cs, tags)


# ---------------- Q9: excluded difficulty levels ----------------
def check_excluded_difficulty(r, qs, difficulty_target):
    excluded = {lvl for lvl, pct in difficulty_target.items() if pct == 0}
    if not excluded:
        return
    for q in qs:
        items = list(leaves_with_location(q)) if isinstance(q.get("parts"), list) else [(q, where(q.get("number")))]
        for obj, loc in items:
            if obj.get("difficulty") in excluded:
                r.error(loc, f"is {obj['difficulty']}, but the spec's difficulty target for "
                             f"{obj['difficulty']} is 0%", "Q9")


# ---------------- Q10: every chapter in the compulsory section ----------------
def check_compulsory_coverage(r, qs, spec_sections, chapters):
    compulsory = {sid for sid, s in spec_sections.items() if s["questionsOffered"] == s["questionsToAttempt"]}
    covered = {q.get("chapter") for q in qs if q.get("section") in compulsory}
    missing = sorted(set(chapters) - covered)
    if missing:
        names = ", ".join(sorted(compulsory))
        r.error(f"section {names}" if len(compulsory) == 1 else f"sections {names}",
                f"no compulsory question from chapter(s) {', '.join(map(str, missing))}; the spec requires "
                "every chapter to appear in the compulsory section(s)", "Q10")


# ---------------- Q11-Q14: balance (warnings) ----------------
def pct(part, whole):
    return float(part) * 100 / float(whole) if whole else 0.0


def marked_items(q):
    """(marks, kind, difficulty) for every leaf, or for the MCQ itself."""
    if isinstance(q.get("parts"), list):
        for leaf, _ in leaves_with_location(q):
            if is_num(leaf.get("marks")):
                yield frac(leaf["marks"]), leaf.get("kind"), leaf.get("difficulty")
    elif is_num(q.get("marks")):
        yield frac(q["marks"]), q.get("kind"), q.get("difficulty")


def check_balance(r, qs, chapters, rules):
    by_chapter = {c: Fraction(0) for c in chapters}
    by_kind, by_level = {}, {}
    for q in qs:
        if q.get("chapter") in by_chapter and is_num(q.get("marks")):
            by_chapter[q["chapter"]] += frac(q["marks"])
        for m, kind, level in marked_items(q):
            by_kind[kind] = by_kind.get(kind, 0) + m
            by_level[level] = by_level.get(level, 0) + m
    offered = sum(by_chapter.values())
    if not offered:
        return

    # Q11: chapters
    cw = rules["chapterWeightage"]
    tol = frac(cw["toleranceMarks"])
    if cw["mode"] == "custom":
        targets = {c: offered * frac(cw["weights"][str(c)]) / 100 for c in chapters}
    else:
        targets = {c: offered / len(chapters) for c in chapters}
    r.info.append("Marks offered by chapter: " + ", ".join(
        f"ch{c} {fmt(float(by_chapter[c]))} (target {float(targets[c]):.1f})" for c in chapters))
    off = [c for c in chapters if abs(by_chapter[c] - targets[c]) > tol]
    if off:
        r.warn("chapters", "outside the tolerance of ±" + fmt(cw["toleranceMarks"]) + " marks: " + "; ".join(
            f"chapter {c} has {fmt(float(by_chapter[c]))} marks (target {float(targets[c]):.1f})" for c in off), "Q11")

    # Q12: numerical / theory
    nts = rules["numericalTheorySplit"]
    num_pct = pct(by_kind.get("numerical", 0), offered)
    r.info.append(f"Numerical/theory: {num_pct:.1f}% / {100 - num_pct:.1f}% "
                  f"(target {fmt(nts['target'][0])}% / {fmt(nts['target'][1])}%)")
    if abs(num_pct - nts["target"][0]) > nts["tolerancePercent"]:
        r.warn("numerical/theory", f"numerical is {num_pct:.1f}% of marks offered, outside the target "
                                   f"{fmt(nts['target'][0])}% ± {fmt(nts['tolerancePercent'])}", "Q12")

    # Q13: difficulty
    dt = rules["difficulty"]
    levels = list(dt["target"])
    actual = {lvl: pct(by_level.get(lvl, 0), offered) for lvl in levels}
    r.info.append("Difficulty: " + ", ".join(
        f"{lvl} {actual[lvl]:.1f}% (target {fmt(dt['target'][lvl])}%)" for lvl in levels))
    off = [lvl for lvl in levels if abs(actual[lvl] - dt["target"][lvl]) > dt["tolerancePercent"]]
    if off:
        r.warn("difficulty", f"outside the tolerance of ±{fmt(dt['tolerancePercent'])}%: " + "; ".join(
            f"{lvl} is {actual[lvl]:.1f}% (target {fmt(dt['target'][lvl])}%)" for lvl in off), "Q13")


def check_shared_concepts(r, qs):
    users = {}
    for q in qs:
        for t in q.get("concepts") or []:
            if isinstance(t, str) and q.get("number") not in users.setdefault(t, []):
                users[t].append(q.get("number"))
    for t, nums in users.items():
        if len(nums) > 1:
            listed = " and ".join(f"Q{n}" for n in nums) if len(nums) == 2 else \
                ", ".join(f"Q{n}" for n in nums[:-1]) + f" and Q{nums[-1]}"
            r.warn(f"concept '{t}'", f"is used by {listed}; check they don't test the same thing", "Q14")


# ---------------- Q15: match the blueprint ----------------
def compare_parts(r, qnum, labels, q_parts, b_parts):
    loc = where(qnum, labels)
    if not isinstance(q_parts, list):
        r.error(loc, "parts must be a list", "Q15")
        return
    if len(q_parts) != len(b_parts):
        r.error(loc, f"has {len(q_parts)} parts but the blueprint has {len(b_parts)}", "Q15")
    for qp, bp in zip(q_parts, b_parts):
        if not isinstance(qp, dict):
            continue
        b_label = bp.get("label")
        ploc = where(qnum, labels + (b_label,))
        if qp.get("label") != b_label:
            r.error(ploc, f"label is {show(qp.get('label'))} but the blueprint says {show(b_label)}", "Q15")
        is_group_q, is_group_b = "parts" in qp, "parts" in bp
        if is_group_q != is_group_b:
            want = "sub-parts" if is_group_b else "no sub-parts"
            r.error(ploc, f"the blueprint says this part has {want}", "Q15")
            continue
        for f in (("marks",) if is_group_b else ("marks", "kind", "difficulty", "concept")):
            if qp.get(f) != bp.get(f):
                r.error(ploc, f"{f} is {show(qp.get(f))} but the blueprint says {show(bp.get(f))}", "Q15")
        if is_group_b:
            compare_parts(r, qnum, labels + (b_label,), qp["parts"], bp["parts"])


def compare_to_blueprint(r, qdoc, bdoc, approved):
    if approved is False:
        r.error("blueprint", "is not approved as it is now: questions may only be written from an "
                             "approved blueprint", "Q15")
    for f in ("spec", "conceptList"):
        if qdoc.get(f) != bdoc.get(f):
            r.error(f, f"is {show(qdoc.get(f))} but the blueprint says {show(bdoc.get(f))}", "Q15")
    qs, bs = qdoc.get("questions"), bdoc.get("questions")
    if not isinstance(qs, list) or not isinstance(bs, list):
        r.error("questions", "both files must have a 'questions' list", "Q15")
        return
    if len(qs) != len(bs):
        r.error("questions", f"there are {len(qs)} questions but the blueprint has {len(bs)}", "Q15")
    no_letter = []
    for i, (q, b) in enumerate(zip(qs, bs)):
        bnum = b.get("number", i + 1)
        loc = where(bnum)
        if not isinstance(q, dict):
            continue
        for f in ("number", "section", "chapter", "marks"):
            if q.get(f) != b.get(f):
                r.error(loc, f"{f} is {show(q.get(f))} but the blueprint says {show(b.get(f))}", "Q15")
        qc, bc = q.get("concepts"), b.get("concepts") or []
        if isinstance(qc, list) and set(qc) != set(bc):
            missing, extra = sorted(set(bc) - set(qc)), sorted(set(qc) - set(bc))
            msg = [f"missing {', '.join(missing)}"] * bool(missing) + [f"extra {', '.join(extra)}"] * bool(extra)
            r.error(loc, "concepts differ from the blueprint: " + "; ".join(msg), "Q15")
        if "parts" in b:
            if "parts" not in q:
                r.error(loc, "the blueprint says this question has parts", "Q15")
            else:
                compare_parts(r, bnum, (), q["parts"], b["parts"])
        else:
            if "parts" in q:
                r.error(loc, "the blueprint says this question has no parts", "Q15")
            if "options" in q and "correctOption" not in b:
                no_letter.append(where(bnum))
            for f in ("kind", "difficulty", "concept", "correctOption"):
                if f == "correctOption" and f not in b:
                    continue
                if q.get(f) != b.get(f):
                    r.error(loc, f"{f} is {show(q.get(f))} but the blueprint says {show(b.get(f))}", "Q15")
    if no_letter:
        r.error("blueprint", f"gives no correctOption for {', '.join(no_letter)}; it was made by an older "
                             "make_blueprint.py: make it again", "Q15")


# ---------------- entry points ----------------
def check(qdoc, bdoc=None, spec=None, concepts=None, blueprint_approved=None):
    """Run every rule that the given inputs allow. Returns a Report. blueprint_approved is None when
    the approval is not checked (render.py, tests of single rules)."""
    r = Report()
    spec_sections, numbering, smu = {}, Numbering.CONTINUOUS, None
    chapters, content_rules = [], {}
    if spec is not None:
        sr = validate_spec(spec)
        if sr.errors:
            r.error("spec", f"has {len(sr.errors)} error(s); fix it with validate_paper_spec.py first. "
                            "Rules that need the spec were skipped", "S")
        else:
            spec_sections = {s["id"]: s for s in spec["pattern"]["sections"]}
            numbering = spec["pattern"]["numbering"]
            smu = spec["pattern"]["smallestMarkUnit"]
            chapters = spec["exam"]["chapters"]
            content_rules = spec["content"]

    if not isinstance(qdoc, dict):
        r.error("file", "must be a JSON object", "Q1")
        return r
    qs = check_fields(r, qdoc, spec_sections)
    if spec_sections:
        check_sequence(r, qs, spec_sections, numbering)
        check_labels(r, qs, spec_sections)
        check_section_counts(r, qs, spec_sections)
        check_mcqs(r, qs, spec_sections)
        check_part_counts(r, qs, spec_sections)
    check_marks(r, qs, smu)
    check_answers(r, qs)
    check_math(r, qs)
    tags = read_concept_list(r, concepts, spec if spec_sections else None) if concepts is not None else None
    check_concepts(r, qs, tags, chapters)
    if content_rules:
        check_excluded_difficulty(r, qs, content_rules["difficulty"]["target"])
        if content_rules["everyChapterInCompulsorySection"]:
            check_compulsory_coverage(r, qs, spec_sections, chapters)
        check_balance(r, qs, chapters, content_rules)
        if content_rules["avoidOverlappingConcepts"]:
            check_shared_concepts(r, qs)
    if bdoc is not None:
        compare_to_blueprint(r, qdoc, bdoc, blueprint_approved)
    return r


def main(argv):
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    bpath = None
    if "--blueprint" in args:
        i = args.index("--blueprint")
        if i + 1 >= len(args):
            print("--blueprint needs a file path")
            return 2
        bpath = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    qpath = args[0]
    folder = os.path.dirname(qpath)
    bpath = bpath or os.path.join(folder, "blueprint.json")
    try:
        qdoc = load_json(qpath)
        if not isinstance(qdoc, dict):
            raise ValueError("questions file must be a JSON object")
        spath = os.path.join(folder, qdoc.get("spec", "spec.json"))
        cpath = os.path.normpath(os.path.join(folder, qdoc.get("conceptList", "")))
        spec, bdoc, concepts = load_json(spath), load_json(bpath), load_json(cpath)
        approved = is_approved(os.path.dirname(bpath), "blueprint", bpath)
    except (OSError, ValueError) as e:   # JSONDecodeError is a ValueError
        print(f"Cannot read input: {e}")
        return 2

    r = check(qdoc, bdoc, spec, concepts, approved)
    if as_json:
        print(json.dumps({"passed": not r.errors, "errors": r.errors, "warnings": r.warnings,
                          "info": r.info}, indent=2, ensure_ascii=False))
    else:
        print(f"Questions: {qpath}\nSpec:      {spath}\nBlueprint: {bpath}\nConcepts:  {cpath}")
        for title, items in (("ERRORS", r.errors), ("WARNINGS", r.warnings), ("INFO", r.info)):
            if items:
                print(f"\n{title}:")
                for m in items:
                    print(f"  - {m}")
        print("\nResult: " + ("PASSED" if not r.errors else f"FAILED ({len(r.errors)} error(s))"))
    return 0 if not r.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
