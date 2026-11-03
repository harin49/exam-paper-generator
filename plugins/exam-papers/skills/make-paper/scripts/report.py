"""What the checking scripts share: the Report that collects their messages, and the small value
checks they use. Every message starts with its rule number, e.g. "[S6] pattern.sections[B]: ...".
"""
from fractions import Fraction


class Report:
    def __init__(self):
        self.errors, self.warnings, self.info = [], [], []

    @staticmethod
    def _fmt(path, msg, rule):
        text = f"{path}: {msg}" if path else msg
        return f"[{rule}] {text}" if rule else text

    def error(self, path, msg, rule=None):
        self.errors.append(self._fmt(path, msg, rule))

    def warn(self, path, msg, rule=None):
        self.warnings.append(self._fmt(path, msg, rule))


def keys_ok(r, obj, allowed, required, loc, rule):
    """Report every required field missing from obj and every field not allowed, under rule."""
    for k in sorted(required - set(obj)):
        r.error(loc, f"'{k}' is required", rule)
    for k in sorted(set(obj) - allowed):
        r.error(loc, f"unknown field '{k}'", rule)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def frac(x):
    return Fraction(str(x))


def fmt(x):
    return f"{x:g}" if isinstance(x, float) else str(x)
