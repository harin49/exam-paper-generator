---
description: Decide the open review findings of the current exam paper (accept or reject each). The teacher types this; Claude cannot.
argument-hint: accept R2 R4 reject R5 [paper folder]
disable-model-invocation: true
---

The teacher typed `/exam-papers:decide $ARGUMENTS`. The exam-papers hook has already checked it
and recorded it in the paper's `review/decisions.json`; its note says which paper, what was
accepted and rejected, and what is next.

Do not write, edit or copy `decisions.json`. If the teacher gave reasons or instructions in chat for
the accepted findings, pass them to the writer. Run `next_step.py` on that paper's folder and carry
on with the step it prints, as the make-paper skill says.
