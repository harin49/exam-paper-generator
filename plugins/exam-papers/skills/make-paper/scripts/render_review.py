#!/usr/bin/env python3
"""Turn the reviewer's findings (review/reviewer-report.json) into review/reviewer-report.html.

Usage:
    python3 render_review.py REPORT.json [--out FILE]
    python3 render_review.py REPORT.json --print

The reviewer subagent writes REPORT.json (format: schemas/review-format.md) and runs this script.
The HTML goes beside REPORT.json with the same name (or to FILE). If that file already holds exactly
the same page, it is left untouched, so a rerun never looks like a change to the workflow.

--print checks the file and prints the findings, and writes nothing. Use it to show the findings
again after the reviewer has finished. The paper's details in the page
heading come from spec.json in the task folder (the folder above review/), if it is there.

The findings are also printed as plain text, in the order and wording of the file, so they can be
shown to the user verbatim.

Rules checked before anything is written:
    every finding has exactly the fields id, severity, location, problem, evidence, suggestedFix,
    each a non-empty string; severity is error, warning or suggestion; ids run R1, R2, ... in order;
    errors come first, then warnings, then suggestions.

Exit codes:
    0  the HTML was written (or was already up to date, or --print)
    1  the findings file breaks a rule above (nothing is written)
    2  the file could not be read or is not valid JSON
"""
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import chapter_list, class_text  # noqa: E402

SEVERITIES = ["error", "warning", "suggestion"]
FIELDS = ["id", "severity", "location", "problem", "evidence", "suggestedFix"]
LABELS = [("problem", "Problem"), ("evidence", "Evidence"), ("suggestedFix", "Suggested fix")]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(doc):
    """List of problems with the findings file (empty when it is valid)."""
    if not isinstance(doc, dict) or set(doc) != {"findings"} or not isinstance(doc["findings"], list):
        return ['the file must be an object with one field, "findings", holding a list']
    errors, last = [], 0
    for i, f in enumerate(doc["findings"], 1):
        where = f"finding {i}"
        if not isinstance(f, dict):
            errors.append(f"{where}: must be an object")
            continue
        missing, unknown = [k for k in FIELDS if k not in f], sorted(set(f) - set(FIELDS))
        if missing:
            errors.append(f"{where}: missing {', '.join(missing)}")
        if unknown:
            errors.append(f"{where}: unknown field {', '.join(unknown)}")
        for k in FIELDS:
            if k in f and not (isinstance(f[k], str) and f[k].strip()):
                errors.append(f"{where}: {k} must be non-empty text")
        if f.get("id") != f"R{i}":
            errors.append(f"{where}: id must be R{i}, not {f.get('id')!r}")
        sev = f.get("severity")
        if sev not in SEVERITIES:
            errors.append(f"{where}: severity must be error, warning or suggestion, not {sev!r}")
        elif SEVERITIES.index(sev) < last:
            errors.append(f"{where}: {sev} comes after a less severe finding (errors, then warnings, "
                          "then suggestions)")
        else:
            last = SEVERITIES.index(sev)
    return errors


def counts_line(findings):
    if not findings:
        return "Findings: none"
    n = {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}
    parts = [f"{n[s]} {s}{'' if n[s] == 1 else 's'}" for s in SEVERITIES]
    return f"Findings: {len(findings)} ({', '.join(parts)})"


def text_report(findings):
    lines = ["# Review of questions.json", counts_line(findings)]
    for f in findings:
        lines += ["", f"## {f['id']}  {f['location']}  {f['severity']}"]
        lines += [f"{label}: {f[key]}" for key, label in LABELS]
    return "\n".join(lines)


def paper_line(spec):
    try:
        ex = spec["exam"]
        return (f"{ex['subject']} · Class {class_text(ex['class'])} ({ex['board']}) · "
                f"Chapters {chapter_list(ex['chapters'])} · {spec['pattern']['totalMarks']} marks")
    except (KeyError, TypeError):
        return ""


def esc(text):
    return html.escape(text).replace("\n", "<br>")


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#5f5f5a;--line:#e3e2dd;
--error:#b42318;--error-bg:#fdecea;--warning:#9a5b00;--warning-bg:#fff4e0;
--suggestion:#24569b;--suggestion-bg:#e8f0fb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--card:#1f1f1e;
--ink:#ecebe6;--muted:#a3a29c;--line:#34332f;--error:#ff8a80;--error-bg:#3a1d1b;--warning:#f3b95f;
--warning-bg:#382a14;--suggestion:#8db8f2;--suggestion-bg:#1b2a3d}}
:root[data-theme="dark"]{--bg:#161615;--card:#1f1f1e;--ink:#ecebe6;--muted:#a3a29c;--line:#34332f;
--error:#ff8a80;--error-bg:#3a1d1b;--warning:#f3b95f;--warning-bg:#382a14;--suggestion:#8db8f2;
--suggestion-bg:#1b2a3d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 16px 64px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px}
.paper{color:var(--muted);margin:0 0 20px}
.summary{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 28px}
.chip{border-radius:999px;padding:4px 12px;font-size:14px;font-weight:600;background:var(--card);
border:1px solid var(--line)}
.chip.error{color:var(--error);background:var(--error-bg);border-color:transparent}
.chip.warning{color:var(--warning);background:var(--warning-bg);border-color:transparent}
.chip.suggestion{color:var(--suggestion);background:var(--suggestion-bg);border-color:transparent}
.finding{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);
border-radius:10px;padding:18px 20px;margin:0 0 14px;break-inside:avoid}
.finding.error{border-left-color:var(--error)}
.finding.warning{border-left-color:var(--warning)}
.finding.suggestion{border-left-color:var(--suggestion)}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 12px}
.id{font-weight:700;font-size:18px}
.badge{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;border-radius:6px;
padding:2px 8px}
.badge.error{color:var(--error);background:var(--error-bg)}
.badge.warning{color:var(--warning);background:var(--warning-bg)}
.badge.suggestion{color:var(--suggestion);background:var(--suggestion-bg)}
.loc{color:var(--muted);font-weight:600;overflow-wrap:anywhere}
dl{margin:0;display:grid;grid-template-columns:120px 1fr;gap:8px 16px}
dt{color:var(--muted);font-size:14px;font-weight:600;padding-top:1px}
dd{margin:0;overflow-wrap:anywhere}
.none{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
@media (max-width:560px){dl{grid-template-columns:1fr;gap:2px}dd{margin-bottom:10px}}
@media print{body{background:#fff}main{padding:0}.finding{border-color:#ccc}}
"""


def html_report(findings, spec):
    n = {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}
    chips = "".join(f'<span class="chip {s}">{n[s]} {s}{"" if n[s] == 1 else "s"}</span>'
                    for s in SEVERITIES)
    cards = []
    for f in findings:
        rows = "".join(f"<dt>{label}</dt><dd>{esc(f[key])}</dd>" for key, label in LABELS)
        cards.append(f'<section class="finding {f["severity"]}" id="{f["id"]}">'
                     f'<div class="head"><span class="id">{f["id"]}</span>'
                     f'<span class="badge {f["severity"]}">{f["severity"]}</span>'
                     f'<span class="loc">{esc(f["location"])}</span></div><dl>{rows}</dl></section>')
    body = "".join(cards) or '<p class="none">The reviewer found nothing to report.</p>'
    paper = paper_line(spec)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Review Report</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Review of questions.json</h1>
{f'<p class="paper">{esc(paper)}</p>' if paper else ''}
<div class="summary"><span class="chip">{len(findings)} finding{"" if len(findings) == 1 else "s"}</span>{chips}</div>
{body}
</main>
</body>
</html>
"""


def main(argv):
    args = argv[1:]
    print_only = "--print" in args
    args = [a for a in args if a != "--print"]
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a file path")
            return 2
        out = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or (print_only and out):
        print(__doc__.strip())
        return 2
    path = args[0]
    try:
        doc = load(path)
    except (OSError, ValueError) as e:   # JSONDecodeError is a ValueError
        print(f"Cannot read input: {e}")
        return 2
    errors = check(doc)
    if errors:
        print(f"{path} breaks the findings format; nothing was written:")
        for e in errors:
            print(f"  - {e}")
        return 1
    if print_only:
        print(text_report(doc["findings"]))
        return 0
    spec_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "spec.json")
    try:
        spec = load(spec_path)
    except (OSError, ValueError):
        spec = {}
    out = out or os.path.splitext(path)[0] + ".html"
    page = html_report(doc["findings"], spec)
    try:
        with open(out, encoding="utf-8") as f:
            unchanged = f.read() == page
    except OSError:
        unchanged = False
    if not unchanged:
        with open(out, "w", encoding="utf-8") as f:
            f.write(page)
    print(text_report(doc["findings"]))
    print(f"\n{out} is already up to date" if unchanged else f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
