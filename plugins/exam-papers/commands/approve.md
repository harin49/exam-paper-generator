---
description: Approve the current paper's blueprint or final paper. The teacher types this; Claude cannot.
argument-hint: blueprint|paper [paper folder]
disable-model-invocation: true
---

The teacher typed `/exam-papers:approve $ARGUMENTS`. The exam-papers approval hook has already
checked it and recorded it in the paper's `approvals.json`; its note says which paper and file.

Do not write, edit or copy `approvals.json`. Run `next_step.py` on that paper's folder and carry on
with the step it prints, as the make-paper skill says.
