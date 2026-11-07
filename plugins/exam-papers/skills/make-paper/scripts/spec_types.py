"""Fixed values shared by the exam-paper scripts (paper spec, blueprint, questions).

Each enum member is also a plain string, so it compares equal to the value read from JSON:
    SectionType.MCQ == "mcq"  ->  True
Use Enum.values() for membership checks and error messages.
"""
import re
from enum import Enum

# A syllabus pack's folder name under syllabi/, e.g. "icse9-physics-selina" (spec: exam.syllabusPack).
PACK_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class _StrEnum(str, Enum):
    """A str-valued Enum (Python 3.10 has no built-in StrEnum)."""

    def __str__(self):
        return self.value

    @classmethod
    def values(cls):
        return {m.value for m in cls}


class SectionType(_StrEnum):
    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"
    LONG_ANSWER = "long_answer"


class SubParts(_StrEnum):
    NONE = "none"
    ALLOWED = "allowed"
    REQUIRED = "required"


class Numbering(_StrEnum):
    CONTINUOUS = "continuous"
    PER_SECTION = "per_section"


class WeightMode(_StrEnum):
    EQUAL = "equal"
    CUSTOM = "custom"


class Diagrams(_StrEnum):
    NONE = "none"
    ONLY_IF_ESSENTIAL = "only_if_essential"
    ALLOWED = "allowed"


class KeyPart(_StrEnum):
    EXPLANATIONS = "explanations"
    MARKING_SCHEME = "markingScheme"


class Kind(_StrEnum):
    NUMERICAL = "numerical"
    THEORY = "theory"


class Difficulty(_StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

