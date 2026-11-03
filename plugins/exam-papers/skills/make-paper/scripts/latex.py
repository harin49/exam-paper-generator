"""LaTeX maths in question text: split it out, check it, and draw it as images for the PDFs.

Maths is written between dollar signs in any printed text field:
    $\\frac{a}{b}$       inline, sitting on the text line
    $$v^2 = u^2 + 2as$$   displayed, on a line of its own, centred
A literal dollar sign is written \\$ ("costs \\$5"). The HTML-style marks (<sup>, <sub>, <b>, <i>)
stay for units and simple cases.

Formulas are typeset by matplotlib's mathtext, which needs no TeX installation. It covers what a
school paper needs (fractions, roots, powers and indices, Greek letters, integrals, relations) but
not LaTeX environments such as \\begin{pmatrix} or aligned equations; check() reports those.
"""
import hashlib
import os
import re

INLINE, DISPLAY, TEXT = "inline", "display", "text"
DPI = 600
MATH_FONTSET = "stix"            # a Times-like maths font, to sit with the serif body text


def split(text):
    """[(kind, content)]: TEXT runs (with \\$ turned into $), INLINE and DISPLAY formulas (without
    their dollar signs). Raises ValueError for an unclosed $ or $$."""
    out, buf, i = [], [], 0
    s = text or ""
    while i < len(s):
        if s.startswith("\\$", i):
            buf.append("$")
            i += 2
            continue
        if s[i] == "$":
            display = s.startswith("$$", i)
            mark = "$$" if display else "$"
            end = s.find(mark, i + len(mark))
            while end != -1 and s[end - 1] == "\\":                     # an escaped $ inside
                end = s.find(mark, end + 1)
            if end == -1:
                raise ValueError(f"an opening {mark} has no closing {mark}: {s[i:i + 40]!r}")
            if buf:
                out.append((TEXT, "".join(buf)))
                buf = []
            tex = s[i + len(mark):end]
            if not tex.strip():
                raise ValueError(f"an empty formula {mark}{mark}")
            out.append((DISPLAY if display else INLINE, tex))
            i = end + len(mark)
            continue
        buf.append(s[i])
        i += 1
    if buf:
        out.append((TEXT, "".join(buf)))
    return out


def has_math(text):
    return any(kind != TEXT for kind, _ in split_quiet(text))


def split_quiet(text):
    """split(), but an unclosed $ is treated as text (for code that must not fail, e.g. messages)."""
    try:
        return split(text)
    except ValueError:
        return [(TEXT, (text or "").replace("\\$", "$"))]


def _parser():
    from matplotlib.mathtext import MathTextParser
    return MathTextParser("agg")


def _typeset(tex, size_pt, dpi):
    import matplotlib
    from matplotlib.font_manager import FontProperties
    with matplotlib.rc_context({"mathtext.fontset": MATH_FONTSET}):
        return _parser().parse(f"${tex}$", dpi=dpi, prop=FontProperties(size=size_pt, family="serif"))


def problems(text):
    """Why the text's maths cannot be typeset: an empty list when it can."""
    try:
        parts = split(text)
    except ValueError as e:
        return [str(e)]
    out = []
    for kind, tex in parts:
        if kind == TEXT:
            continue
        try:
            _typeset(tex, 10, 72)
        except Exception as e:                       # mathtext raises ValueError subclasses and others
            out.append(f"${tex}$ cannot be typeset: {reason(e)}")
    return out


def reason(error):
    """The useful line of a mathtext error ("Unknown symbol: \\begin", "Expected \\frac{num}{den}")."""
    lines = [l.strip() for l in str(error).splitlines() if l.strip()]
    last = lines[-1] if lines else "cannot be typeset"
    last = re.sub(r"^Parse\w*Exception:\s*", "", last)
    last = re.sub(r",?\s*\(at char \d+\).*$", "", last)
    if last.startswith("Expected {phantom"):
        last = "something is missing (e.g. a ^ or _ with nothing after it)"
    return last[:140]


def image(tex, size_pt, folder, display=False):
    """Draw a formula as a transparent PNG in folder. Returns (path, width_pt, height_pt, depth_pt),
    the depth being how far it reaches below the text baseline."""
    from PIL import Image
    size = size_pt * (1.15 if display else 1.0)
    key = hashlib.sha256(f"{tex}|{size}|{MATH_FONTSET}".encode()).hexdigest()[:16]
    path = os.path.join(folder, f"math-{key}.png")
    r = _typeset(tex, size, DPI)
    if not os.path.exists(path):
        alpha = Image.fromarray(r.image)
        png = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
        png.putalpha(alpha)
        png.save(path)
    scale = 72 / DPI
    return path, r.width * scale, r.height * scale, r.depth * scale


# ---- reading a number written in LaTeX (for the MCQ value check, Q4) ----
LATEX_NUMBER_MARKS = [
    (re.compile(r"\\times"), "×"), (re.compile(r"\\cdot"), "×"),
    (re.compile(r"10\s*\^\s*\{\s*([−-]?\d+)\s*\}"), r"10<sup>\1</sup>"),
    (re.compile(r"10\s*\^\s*([−-]?\d)"), r"10<sup>\1</sup>"),
    (re.compile(r"\{,\}"), ","), (re.compile(r"\\[,;!: ]"), " "), (re.compile(r"\\mathrm\{([^}]*)\}"), r"\1"),
]


def number_marks(text):
    """The text with a leading inline formula rewritten in the HTML-style marks the value check reads:
    "$4.5 \\times 10^{3}$ N" becomes "4.5 × 10<sup>3</sup> N". Other text is returned unchanged."""
    parts = split_quiet(text)
    if not parts or parts[0][0] != INLINE:
        return text
    tex = parts[0][1]
    for rx, rep in LATEX_NUMBER_MARKS:
        tex = rx.sub(rep, tex)
    rest = "".join(c if k == TEXT else f"${c}$" for k, c in parts[1:])
    return tex.strip() + rest
