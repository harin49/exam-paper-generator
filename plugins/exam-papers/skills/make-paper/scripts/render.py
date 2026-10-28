#!/usr/bin/env python3
"""Render the question paper and the answer key (two PDFs) from a questions.json file.

Usage:
    python3 render.py QUESTIONS.json [--out DIR] [--blueprint FILE]

The spec and concept list are the files named in QUESTIONS.json's "spec" and "conceptList" fields
(relative to its folder). The blueprint defaults to blueprint.json in the same folder (it is
optional here; when it is missing, Q15 is skipped). PDFs go to DIR (default: the folder of
QUESTIONS.json, which is the paper's task folder under papers/).

check_questions.py runs first. If any hard rule fails the PDFs are not built (exit code 1);
warnings are printed and the build goes ahead.

Everything printed that is not question wording comes from the spec: the time allowed, the maximum
marks, the section headings and the general instructions, the constants, and what the answer key
includes (output.answerKey.include). Diagrams are placed from the image files named in the
questions ("diagram" on the paper, "answerDiagram" in the key). If an image is missing, a labelled
placeholder box is printed in its place and the build ends with a warning that lists it.

Fonts: the first installed family from FONT_FAMILIES (Times New Roman, Liberation Serif, DejaVu
Serif) that has every character the paper uses. Nothing is bundled.

Exit codes:
    0  both PDFs built (warnings may still be printed)
    1  the questions failed check_questions.py, or no usable font was found
    2  a file could not be read or is not valid JSON
"""
import json
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_questions import check  # noqa: E402
from spec_types import SectionType  # noqa: E402

# --------------------------------------------------------------------------------------------
# Text helpers (pure functions, no reportlab needed)
# --------------------------------------------------------------------------------------------
NBSP = "\u00a0"
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
         "nineteen", "twenty"]
ROMAN_CLASS = {5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII"}

# Unit symbols that are kept on the same line as the number before them.
UNIT_TOKENS = ["km", "m", "cm", "mm", "kg", "g", "mg", "s", "ms", "min", "h", "N", "kN", "Pa", "kPa", "J",
               "kJ", "W", "kW", "Hz", "K", "A", "V", "C", "mol", "L", "mL", "°C", "°", "cm³", "m³",
               "kgf", "gf", "dyne", "erg", "cal", "kcal", "atm", "bar", "rad"]
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNIT_TOKENS), key=len, reverse=True))
RE_NUM_UNIT = re.compile(r"(?<=[\d>]) (?=(?:%s)(?![A-Za-z]))" % _UNIT_ALT)
RE_UNIT_CHAIN = re.compile(r"\b(?:(?:%s) )+(?:%s)(?=<sup>)" % (_UNIT_ALT, _UNIT_ALT))
RE_SUP_CHAIN = re.compile(r"(?<=</sup>) (?=(?:%s)(?:<sup>|(?![A-Za-z])))" % _UNIT_ALT)
RE_CHAIN_AFTER_NUM = re.compile(r"( (?:%s)) (?=(?:%s)(?![A-Za-z]))" % (_UNIT_ALT, _UNIT_ALT))
RE_TIMES = re.compile(r"(?<=[\d>]) × (?=\d)")
# A one-letter symbol (optionally subscripted) is kept with "= value": "g = 9.8", "F<sub>2</sub> = 50".
RE_SYMBOL_EQ = re.compile(r"(?<![^\W\d_])([^\W\d_](?:<sub>[^<]*</sub>)?) = (?=[−-]?\d)")
RE_ALLOWED_TAG = re.compile(r"</?(?:sup|sub|b|i)>|<br\s*/?>")

KNOWN_CONSTANTS = {"g": ("g", "m s<sup>−2</sup>")}


def fmt_marks(x):
    """0.5 -> '½', 1.5 -> '1½', 3 -> '3'."""
    x = Fraction(str(x)).limit_denominator(100)
    whole, rest = divmod(x, 1)
    sym = {Fraction(1, 2): "½", Fraction(1, 4): "¼", Fraction(3, 4): "¾"}.get(rest)
    if rest == 0:
        return str(whole)
    if sym:
        return sym if whole == 0 else f"{whole}{sym}"
    return f"{float(x):g}"


def marks_word(x):
    return "mark" if Fraction(str(x)) == 1 else "marks"


def number_word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def duration_text(minutes):
    h, m = divmod(int(minutes), 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    return " ".join(parts) or "0 minutes"


def chapter_list(chapters):
    """[1, 2, 3, 4, 5] -> '1–5'; [1, 3, 5] -> '1, 3, 5'."""
    cs = sorted(chapters)
    if len(cs) > 2 and cs == list(range(cs[0], cs[-1] + 1)):
        return f"{cs[0]}–{cs[-1]}"
    return ", ".join(str(c) for c in cs)


def class_text(n):
    return ROMAN_CLASS.get(n, str(n))


def markup(text):
    """Convert question text (the small HTML-like markup) into reportlab paragraph markup.

    Allowed tags are <sup>, <sub>, <b>, <i> and <br/>; any other '<', '>' or '&' is printed as
    written. A value is kept on one line with its unit (a normal space becomes a no-break space).
    """
    out, pos = [], 0
    for m in RE_ALLOWED_TAG.finditer(text):
        out.append(_escape(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_escape(text[pos:]))
    s = "".join(out)
    s = RE_NUM_UNIT.sub(NBSP, s)
    s = RE_UNIT_CHAIN.sub(lambda m: m.group(0).replace(" ", NBSP), s)
    s = RE_SUP_CHAIN.sub(NBSP, s)
    s = RE_TIMES.sub(NBSP + "×" + NBSP, s)
    s = RE_SYMBOL_EQ.sub("\\1" + NBSP + "=" + NBSP, s)
    # A unit already glued to a number pulls the next unit symbol in too ("5 N m" stays together).
    for _ in range(3):
        s = RE_CHAIN_AFTER_NUM.sub("\\1" + NBSP, s)
    return s.replace("<sup>", "<super>").replace("</sup>", "</super>")


def _escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(text):
    """Text with markup removed (for font coverage and messages)."""
    return re.sub(r"<[^>]*>", "", text or "")


def section_line(section):
    """'Attempt any FIVE questions.' / 'Answer all questions.'"""
    offered, attempt = section["questionsOffered"], section["questionsToAttempt"]
    if attempt == offered:
        return "Answer all questions."
    return f"Attempt any {number_word(attempt).upper()} question{'' if attempt == 1 else 's'}."


def section_subtitle(section):
    m = section["marksPerQuestion"]
    return (f"{section_line(section)} Each question carries {fmt_marks(m)} {marks_word(m)}. "
            f"[{section['questionsToAttempt']} × {fmt_marks(m)} = {fmt_marks(section['sectionTotal'])}]")


def constants_text(constants):
    parts = []
    for name, value in constants.items():
        sym, unit = KNOWN_CONSTANTS.get(name, (name.replace("_", " "), ""))
        v = f"{value:g}"
        parts.append(f"{sym}{NBSP}={NBSP}{v}" + (f"{NBSP}{unit}" if unit else ""))
    return ", ".join(parts)


def instructions(spec, has_numerical, has_subparts):
    """The general instructions printed at the top of the question paper (markup text)."""
    secs = spec["pattern"]["sections"]
    ids = [s["id"] for s in secs]
    names = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]
    lines = [f"This paper has {number_word(len(ids))} section{'s' if len(ids) != 1 else ''}: {names}."]
    for s in secs:
        if s["questionsToAttempt"] == s["questionsOffered"]:
            what = "Answer <b>all</b> questions."
        else:
            what = (f"Attempt <b>any {number_word(s['questionsToAttempt'])}</b> "
                    f"question{'' if s['questionsToAttempt'] == 1 else 's'} out of "
                    f"{number_word(s['questionsOffered'])}.")
        lines.append(f"<b>Section {s['id']}</b>: {what}")
    marks = "The marks for each question or part of a question are given in brackets [ ]"
    marks += ("; marks for sub-parts are shown in parentheses ( )." if has_subparts else ".")
    lines.append(marks)
    if has_numerical:
        lines.append("Show all working for numerical problems and write the appropriate unit with "
                     "every answer.")
    consts = spec["content"].get("constants") or {}
    if consts:
        lines.append(f"Take {constants_text(consts)} unless stated otherwise.")
    return [f"{i}. {t}" for i, t in enumerate(lines, 1)]


# --------------------------------------------------------------------------------------------
# Walking the questions
# --------------------------------------------------------------------------------------------
def leaves(parts, prefix=()):
    for p in parts:
        if "parts" in p:
            yield from leaves(p["parts"], prefix + (p["label"],))
        else:
            yield prefix + (p["label"],), p


def paper_facts(qs):
    """(has_numerical, has_subparts) over the whole paper."""
    num = sub = False
    for q in qs:
        if "options" in q:
            num = num or q["kind"] == "numerical"
        else:
            for p in q["parts"]:
                if "parts" in p:
                    sub = True
            for _, leaf in leaves(q["parts"]):
                num = num or leaf["kind"] == "numerical"
    return num, sub


def all_text(qdoc, spec):
    """Every character that may be printed, for the font check."""
    s = json.dumps(qdoc, ensure_ascii=False) + json.dumps(spec.get("output", {}), ensure_ascii=False)
    s += "×—·½¼¾•–“”’[]()≥ " + NBSP
    return {c for c in plain(s) if ord(c) >= 0x20}


# --------------------------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------------------------
FONT_FAMILIES = [
    ("Times New Roman", [
        ["/System/Library/Fonts/Supplemental/Times New Roman.ttf",
         "/Library/Fonts/Times New Roman.ttf", "C:/Windows/Fonts/times.ttf"],
        ["/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
         "/Library/Fonts/Times New Roman Bold.ttf", "C:/Windows/Fonts/timesbd.ttf"],
        ["/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
         "/Library/Fonts/Times New Roman Italic.ttf", "C:/Windows/Fonts/timesi.ttf"],
        ["/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
         "/Library/Fonts/Times New Roman Bold Italic.ttf", "C:/Windows/Fonts/timesbi.ttf"],
    ]),
    ("Liberation Serif", [
        [d + "LiberationSerif-Regular.ttf" for d in ("/usr/share/fonts/truetype/liberation2/",
                                                      "/usr/share/fonts/truetype/liberation/",
                                                      "/usr/share/fonts/liberation/")],
        [d + "LiberationSerif-Bold.ttf" for d in ("/usr/share/fonts/truetype/liberation2/",
                                                   "/usr/share/fonts/truetype/liberation/",
                                                   "/usr/share/fonts/liberation/")],
        [d + "LiberationSerif-Italic.ttf" for d in ("/usr/share/fonts/truetype/liberation2/",
                                                     "/usr/share/fonts/truetype/liberation/",
                                                     "/usr/share/fonts/liberation/")],
        [d + "LiberationSerif-BoldItalic.ttf" for d in ("/usr/share/fonts/truetype/liberation2/",
                                                         "/usr/share/fonts/truetype/liberation/",
                                                         "/usr/share/fonts/liberation/")],
    ]),
    ("DejaVu Serif", [
        [d + "DejaVuSerif.ttf" for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/",
                                         "/usr/share/fonts/TTF/")],
        [d + "DejaVuSerif-Bold.ttf" for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/",
                                              "/usr/share/fonts/TTF/")],
        [d + "DejaVuSerif-Italic.ttf" for d in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/",
                                                "/usr/share/fonts/TTF/")],
        [d + "DejaVuSerif-BoldItalic.ttf" for d in ("/usr/share/fonts/truetype/dejavu/",
                                                    "/usr/share/fonts/dejavu/", "/usr/share/fonts/TTF/")],
    ]),
]


def find_font(needed_chars, families=None):
    """Pick the first family whose four styles are installed and cover every needed character.

    Returns (family_name, [four paths], missing_chars). If no family covers everything, the one
    missing the fewest characters is returned with those characters listed. Returns None when no
    family is installed at all.
    """
    from reportlab.pdfbase.ttfonts import TTFont
    best = None
    for name, styles in (families or FONT_FAMILIES):
        paths = []
        for options in styles:
            hit = next((p for p in options if os.path.isfile(p)), None)
            if hit is None:
                break
            paths.append(hit)
        if len(paths) != 4:
            continue
        cmap = TTFont("probe-" + name, paths[0]).face.charToGlyph
        missing = sorted(c for c in needed_chars if ord(c) not in cmap)
        if not missing:
            return name, paths, []
        if best is None or len(missing) < len(best[2]):
            best = (name, paths, missing)
    return best


def register_fonts(paths):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    from reportlab.pdfbase.ttfonts import TTFont
    for face, path in zip(("Body", "Body-B", "Body-I", "Body-BI"), paths):
        pdfmetrics.registerFont(TTFont(face, path))
    registerFontFamily("Body", normal="Body", bold="Body-B", italic="Body-I", boldItalic="Body-BI")


# --------------------------------------------------------------------------------------------
# PDF building (reportlab)
# --------------------------------------------------------------------------------------------
class Styles:
    def __init__(self):
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.styles import ParagraphStyle
        self.colors = colors
        self.body = ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=14)
        self.small = ParagraphStyle("small", parent=self.body, fontSize=9.5, leading=13)
        self.center = ParagraphStyle("center", parent=self.body, alignment=TA_CENTER)
        self.right = ParagraphStyle("right", parent=self.body, alignment=TA_RIGHT)
        self.marks = ParagraphStyle("marks", parent=self.body, alignment=TA_RIGHT)
        self.title = ParagraphStyle("title", parent=self.body, fontName="Body-B", fontSize=15, leading=20,
                                    alignment=TA_CENTER, spaceAfter=4)
        self.subject = ParagraphStyle("subject", parent=self.body, fontName="Body-B", fontSize=13,
                                      leading=17, alignment=TA_CENTER, spaceAfter=4)
        self.sect = ParagraphStyle("sect", parent=self.body, fontName="Body-B", fontSize=12.5, leading=17,
                                   alignment=TA_CENTER, spaceBefore=6, spaceAfter=1, keepWithNext=1)
        self.sect_free = ParagraphStyle("sect_free", parent=self.sect, keepWithNext=0)
        self.sectsub = ParagraphStyle("sectsub", parent=self.body, fontName="Body-I", alignment=TA_CENTER,
                                      spaceAfter=5, keepWithNext=1)
        self.h3 = ParagraphStyle("h3", parent=self.body, fontName="Body-B", fontSize=11, spaceBefore=8,
                                 spaceAfter=1, keepWithNext=1)
        self.tag = ParagraphStyle("tag", parent=self.small, fontSize=8.5, leading=11,
                                  textColor=colors.HexColor("#666666"), spaceAfter=2, keepWithNext=1)
        self.scheme = ParagraphStyle("scheme", parent=self.small, textColor=colors.HexColor("#1f3d6b"))
        self.caption = ParagraphStyle("caption", parent=self.small, alignment=TA_CENTER, fontName="Body-I")


WIDTH_MM = 170
MARK_COL_MM = 12
NUM_COL_MM = 10
LAB_COL_MM = 8


class Renderer:
    def __init__(self, qdoc, spec, concepts, folder):
        self.qdoc, self.spec, self.concepts, self.folder = qdoc, spec, concepts, folder
        self.qs = qdoc["questions"]
        self.sections = {s["id"]: s for s in spec["pattern"]["sections"]}
        self.st = Styles()
        self.missing = []          # (question number, description, file)

    # ---- small helpers ----
    def P(self, text, style=None):
        from reportlab.platypus import Paragraph
        return Paragraph(markup(text), style or self.st.body)

    def chapter_title(self, n):
        try:
            return self.concepts["chapters"][str(n)]["title"]
        except (KeyError, TypeError):
            return ""

    def diagram(self, q, d, max_mm=110):
        """An image flowable for a diagram, or a labelled placeholder box if the file is missing."""
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, Table, TableStyle
        path = os.path.join(self.folder, d["file"]) if d.get("file") else None
        if path and os.path.isfile(path):
            from reportlab.lib.utils import ImageReader
            w, h = ImageReader(path).getSize()
            width = max_mm * mm
            img = Image(path, width=width, height=width * h / w)
            img.hAlign = "LEFT"
            return img
        self.missing.append((q["number"], d["description"], d.get("file")))
        box = Table([[self.P(f"<b>[Diagram not yet drawn]</b><br/>{d['description']}", self.st.small)]],
                    colWidths=[max_mm * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, self.st.colors.HexColor("#b00020")),
                                 ("BACKGROUND", (0, 0), (-1, -1), self.st.colors.HexColor("#fdecea")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        box.hAlign = "LEFT"
        return box

    def page_template(self, title):
        from reportlab.lib.pagesizes import A4

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Body", 8.5)
            canvas.drawCentredString(A4[0] / 2, 12 * 2.8346, f"Page {doc.page}")
            canvas.restoreState()
        return footer

    # ---- the question paper ----
    def question_table(self, q):
        """One question as a single table: number | label | sub-label | text | marks."""
        from reportlab.lib.units import mm
        from reportlab.platypus import Table, TableStyle
        rows, spans = [], []
        body_w = WIDTH_MM - NUM_COL_MM - 2 * LAB_COL_MM - MARK_COL_MM

        def add(c1="", c2="", c3="", mk="", span=None):
            num = self.P(f"<b>{q['number']}.</b>") if not rows else ""
            rows.append([num, c1, c2, c3, mk])
            if span:
                spans.append(("SPAN", (span[0], len(rows) - 1), (span[1], len(rows) - 1)))

        def bracket(m):
            return self.P(f"[{fmt_marks(m)}]", self.st.marks)

        def paren(m):
            return self.P(f"({fmt_marks(m)})", self.st.marks)

        if self.spec["content"].get("showChapterNames"):
            add(self.P(f"<i>Unit {q['chapter']}: {self.chapter_title(q['chapter'])}</i>", self.st.tag),
                span=(1, 3))
        if "options" in q:
            add(self.P(q["text"]), mk=bracket(q["marks"]), span=(1, 3))
            if "diagram" in q:
                add(self.diagram(q, q["diagram"]), span=(1, 3))
            add(self.options_table(q["options"], (WIDTH_MM - NUM_COL_MM - MARK_COL_MM) * mm), span=(1, 3))
        else:
            if q.get("stem"):
                add(self.P(q["stem"]), span=(1, 3))
            if "diagram" in q:
                add(self.diagram(q, q["diagram"]), span=(1, 3))
            for p in q["parts"]:
                label = f"({p['label']})" if p["label"] else ""
                if "parts" in p:
                    add(self.P(label), self.P(p["text"]), mk=bracket(p["marks"]), span=(2, 3))
                    for sp in p["parts"]:
                        add("", self.P(f"({sp['label']})"), self.P(sp["text"]), paren(sp["marks"]))
                        if "diagram" in sp:
                            add("", "", self.diagram(q, sp["diagram"]))
                elif label:
                    add(self.P(label), self.P(p["text"]), mk=bracket(p["marks"]), span=(2, 3))
                    if "diagram" in p:
                        add("", self.diagram(q, p["diagram"]), span=(2, 3))
                else:
                    add(self.P(p["text"]), mk=bracket(p["marks"]), span=(1, 3))
                    if "diagram" in p:
                        add(self.diagram(q, p["diagram"]), span=(1, 3))
        t = Table(rows, colWidths=[NUM_COL_MM * mm, LAB_COL_MM * mm, LAB_COL_MM * mm, body_w * mm,
                                   MARK_COL_MM * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (4, 0), (4, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ] + spans))
        return t

    def options_table(self, options, width):
        from reportlab.platypus import Table, TableStyle
        letters = "abcdefghij"
        cells = [self.P(f"({letters[i]}) {o}") for i, o in enumerate(options)]
        longest = max(len(plain(o)) for o in options)
        per_row = 2 if (longest <= 36 and len(options) % 2 == 0) else 1
        rows = [cells[i:i + per_row] for i in range(0, len(cells), per_row)]
        for r in rows:
            r.extend([""] * (per_row - len(r)))
        t = Table(rows, colWidths=[width / per_row] * per_row)
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    def build_paper(self, path):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle
        ex, pat, st = self.spec["exam"], self.spec["pattern"], self.st
        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                                topMargin=14 * mm, bottomMargin=18 * mm,
                                title=f"{ex['subject']} Question Paper")
        s = []
        header = self.spec["output"].get("header")
        if header:
            for line in header.split("\n"):
                s.append(self.P(line, st.title))
        s.append(self.P(f"{ex['subject']} — Class {class_text(ex['class'])} ({ex['board']})", st.subject))
        info = Table([[self.P(f"<b>Time allowed:</b> {duration_text(pat['durationMinutes'])}"),
                       self.P(f"<b>Maximum Marks:</b> {fmt_marks(pat['totalMarks'])}", st.right)]],
                     colWidths=[85 * mm, 85 * mm])
        info.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        s += [info, Spacer(1, 4)]
        has_num, has_sub = paper_facts(self.qs)
        lines = ["<b>General Instructions:</b>"] + instructions(self.spec, has_num, has_sub)
        box = Table([[self.P(x, st.small)] for x in lines], colWidths=[WIDTH_MM * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, st.colors.black),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                                 ("TOPPADDING", (0, 0), (0, 0), 5), ("BOTTOMPADDING", (0, -1), (-1, -1), 5)]))
        s.append(box)
        for sec in pat["sections"]:
            s.append(self.P(f"SECTION {sec['id']}", st.sect))
            s.append(self.P(section_subtitle(sec), st.sectsub))
            for q in (q for q in self.qs if q["section"] == sec["id"]):
                s.append(KeepTogether([self.question_table(q)]))
                s.append(Spacer(1, 3 if sec["type"] != SectionType.LONG_ANSWER else 5))
        s += [Spacer(1, 4), self.P("*** End of Question Paper ***", st.center)]
        footer = self.page_template("paper")
        doc.build(s, onFirstPage=footer, onLaterPages=footer)

    # ---- the answer key ----
    def build_key(self, path):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (CondPageBreak, KeepTogether, SimpleDocTemplate, Spacer, Table,
                                        TableStyle)
        ex, pat, st = self.spec["exam"], self.spec["pattern"], self.st
        include = set(self.spec["output"]["answerKey"].get("include", []))
        smu = pat["smallestMarkUnit"]
        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                                topMargin=16 * mm, bottomMargin=20 * mm,
                                title=f"{ex['subject']} Answer Key and Marking Scheme")
        s = [self.P("Answer Key and Marking Scheme", st.title),
             self.P(f"{ex['subject']} — Class {class_text(ex['class'])} ({ex['board']}) · "
                    f"Units {chapter_list(ex['chapters'])} · Maximum Marks: {fmt_marks(pat['totalMarks'])} · "
                    "For teacher use", st.center),
             Spacer(1, 6)]
        notes = ("<b>General marking notes:</b> Award method marks for correct working even if the final "
                 "answer is wrong because of an arithmetic slip. Allow carry-forward of an earlier wrong "
                 "value into later parts where the method is correct. ")
        if "markingScheme" in include:
            notes += (f"Deduct {fmt_marks(smu)} mark (once per part) for a missing or wrong unit on a final "
                      "numerical answer; do not apply this where the part's own scheme already ties marks "
                      "to the unit (no double deduction). Any correct unit is acceptable unless the "
                      "question asks for a specific one. ")
        notes += "Accept any equivalent correct wording for definitions and reasons."
        s.append(self.P(notes, st.small))

        for sec in pat["sections"]:
            qs = [q for q in self.qs if q["section"] == sec["id"]]
            m = sec["marksPerQuestion"]
            kind = {SectionType.MCQ: "Multiple Choice", SectionType.SHORT_ANSWER: "Short Answer",
                    SectionType.LONG_ANSWER: "Long Answer"}.get(sec["type"], "")
            choice = ("" if sec["questionsToAttempt"] == sec["questionsOffered"]
                      else f" (any {number_word(sec['questionsToAttempt'])})")
            s.append(CondPageBreak(60 * mm))
            heading = f"SECTION {sec['id']} — {kind}, {fmt_marks(m)} {marks_word(m)} each{choice}"
            # An MCQ table may run over pages, so its heading must not be glued to the whole table.
            s.append(self.P(heading, st.sect_free if sec["type"] == SectionType.MCQ else st.sect))
            if sec["type"] == SectionType.MCQ:
                s.append(self.mcq_key_table(qs, "explanations" in include))
                s.append(self.P("No partial marks in this section. If more than one option is marked, "
                                "award 0.", st.small))
                continue
            for q in qs:
                s += [KeepTogether(self.answer_block(q, "markingScheme" in include)), Spacer(1, 3)]
        s += [Spacer(1, 10), self.P("*** End of Answer Key ***", st.center)]
        footer = self.page_template("key")
        doc.build(s, onFirstPage=footer, onLaterPages=footer)

    def mcq_key_table(self, qs, explain):
        from reportlab.lib.units import mm
        from reportlab.platypus import Table, TableStyle
        st = self.st
        head = [self.P("<b>Q</b>", st.small), self.P("<b>Ans</b>", st.small)]
        widths = [10 * mm, 38 * mm if explain else 160 * mm]
        if explain:
            head.append(self.P("<b>Explanation</b>", st.small))
            widths.append(122 * mm)
        rows = [head]
        for q in qs:
            i = "abcdefghij".index(q["correctOption"])
            row = [self.P(str(q["number"]), st.small),
                   self.P(f"<b>({q['correctOption']})</b> {q['options'][i]}", st.small)]
            if explain:
                row.append(self.P(q["explanation"], st.small))
            rows.append(row)
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, st.colors.HexColor("#999999")),
                               ("BACKGROUND", (0, 0), (-1, 0), st.colors.HexColor("#e8e8e8")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def answer_block(self, q, show_marking):
        from reportlab.lib.units import mm
        from reportlab.platypus import Spacer, Table, TableStyle
        st = self.st
        total = fmt_marks(q["marks"])
        tags = f"Unit {q['chapter']}"         # spec and question "chapter"s are syllabus units
        title = self.chapter_title(q["chapter"])
        if title:
            tags += f": {title}"
        tags += " · " + ", ".join(q["concepts"])
        block = [self.P(f"Question {q['number']}  [{total} {marks_word(q['marks'])}]", st.h3),
                 self.P(tags, st.tag)]
        for labels, leaf in leaves(q["parts"]):
            lab = "".join(f"({x})" for x in labels if x)
            cells = [[self.P(f"<b>{lab}</b>", st.small), self.P(leaf["answer"], st.small)]]
            if show_marking and leaf.get("marking"):
                items = "<br/>".join(f"• <b>{fmt_marks(m['marks'])}</b> — {m['for']}" for m in leaf["marking"])
                cells.append(["", self.P(f"<b>Marking:</b><br/>{items}", st.scheme)])
            r = Table(cells, colWidths=[22 * mm, 148 * mm])
            r.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                   ("LINEBELOW", (0, -1), (-1, -1), 0.3, st.colors.HexColor("#cccccc"))]))
            block.append(r)
            if "answerDiagram" in leaf:
                block += [Spacer(1, 3), self.diagram(q, leaf["answerDiagram"], max_mm=120),
                          self.P(plain(leaf["answerDiagram"]["description"]), st.caption)]
        return block


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def output_names(spec):
    ex = spec["exam"]
    base = f"{ex['subject']}_Class{ex['class']}".replace(" ", "_")
    return f"{base}_Question_Paper.pdf", f"{base}_Answer_Key.pdf"


def main(argv):
    args = argv[1:]
    out_dir = bpath = None
    for flag in ("--out", "--blueprint"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"{flag} needs a value")
                return 2
            if flag == "--out":
                out_dir = args[i + 1]
            else:
                bpath = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    qpath = args[0]
    folder = os.path.dirname(os.path.abspath(qpath))
    try:
        qdoc = load(qpath)
        if not isinstance(qdoc, dict):
            raise ValueError("questions file must be a JSON object")
        spec = load(os.path.join(folder, qdoc.get("spec", "spec.json")))
        concepts = load(os.path.normpath(os.path.join(folder, qdoc.get("conceptList", ""))))
        bpath = bpath or os.path.join(folder, "blueprint.json")
        bdoc = load(bpath) if os.path.isfile(bpath) else None
    except (OSError, ValueError) as e:
        print(f"Cannot read input: {e}")
        return 2

    report = check(qdoc, bdoc, spec, concepts)
    if report.errors:
        print(f"check_questions.py found {len(report.errors)} error(s); the PDFs were not built:")
        for m in report.errors:
            print(f"  - {m}")
        return 1
    if report.warnings:
        print("Warnings from check_questions.py (the build goes ahead):")
        for m in report.warnings:
            print(f"  - {m}")
    if bdoc is None:
        print(f"Note: no blueprint at {bpath}; rule Q15 was not checked.")

    found = find_font(all_text(qdoc, spec))
    if found is None:
        print("No usable font found. Install Times New Roman, Liberation Serif or DejaVu Serif.")
        return 1
    family, paths, missing = found
    if missing:
        print(f"Warning: font '{family}' has no glyph for: {' '.join(missing)} (they will print as "
              "blanks). Install Liberation Serif or DejaVu Serif for full coverage.")
    register_fonts(paths)

    out_dir = out_dir or folder
    os.makedirs(out_dir, exist_ok=True)
    paper_name, key_name = output_names(spec)
    r = Renderer(qdoc, spec, concepts, folder)
    r.build_paper(os.path.join(out_dir, paper_name))
    paper_missing, r.missing = r.missing, []
    r.build_key(os.path.join(out_dir, key_name))
    key_missing = r.missing

    print(f"Font: {family}")
    print(f"Question paper: {os.path.join(out_dir, paper_name)}")
    print(f"Answer key:     {os.path.join(out_dir, key_name)}")
    seen = {(n, f) for n, _, f in paper_missing + key_missing}
    if seen:
        print(f"\nWARNING: {len(seen)} diagram image(s) are missing; a placeholder box was printed:")
        for n, desc, f in paper_missing + key_missing:
            print(f"  - Q{n}: {f or '(no file named)'}: {desc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
