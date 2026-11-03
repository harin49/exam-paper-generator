"""The shape of a paper, shared by the exam-paper scripts: labels, locations, the walk over a
question's parts, and the names printed or written for it. Standard library only, so any script or
hook can import it.
"""
import re

LETTERS = "abcdefghijklmnopqrstuvwxyz"            # part labels and MCQ option letters
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]   # sub-part labels
ROMAN_CLASS = {5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII"}


def leaves(parts, prefix=()):
    """(labels, part) for every answerable part, sub-parts included; labels is e.g. ('b', 'ii')."""
    for p in parts:
        if "parts" in p:
            yield from leaves(p["parts"], prefix + (p["label"],))
        else:
            yield prefix + (p["label"],), p


def where(qnum, labels=()):
    """Readable location, e.g. Q21(b)(ii)."""
    return f"Q{qnum}" + "".join(f"({l})" for l in labels if l)


def part_id(labels):
    """('b', 'ii') -> 'b(ii)'; ('',) -> ''. The id the blind solver answers each part by."""
    first, rest = labels[0], labels[1:]
    return first if not rest else first + "".join(f"({x})" for x in rest)


def plain_text(s):
    """Question markup -> plain text a model can read exactly."""
    if s is None:
        return None
    s = re.sub(r"<sup>(.*?)</sup>", r"^(\1)", s)
    s = re.sub(r"<sub>(.*?)</sub>", r"_\1", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</?(?:b|i)>", "", s)
    return s.replace(" ", " ")                    # no-break space


def chapter_list(chapters):
    """[1, 2, 3, 4, 5] -> '1–5'; [1, 3, 5] -> '1, 3, 5'."""
    cs = sorted(chapters)
    if len(cs) > 2 and cs == list(range(cs[0], cs[-1] + 1)):
        return f"{cs[0]}–{cs[-1]}"
    return ", ".join(str(c) for c in cs)


def class_text(n):
    return ROMAN_CLASS.get(n, str(n))


def output_names(spec):
    """The file names of the question paper and the answer key PDFs."""
    ex = spec["exam"]
    base = f"{ex['subject']}_Class{ex['class']}".replace(" ", "_")
    return f"{base}_Question_Paper.pdf", f"{base}_Answer_Key.pdf"
