---
description: Approve a syllabus pack's concept list, or the current paper's blueprint or final paper. The teacher types this; Claude cannot.
argument-hint: concepts|blueprint|paper [pack or paper folder]
disable-model-invocation: true
---

The teacher typed `/exam-papers:approve $ARGUMENTS`. The exam-papers approval hook has already
checked it and recorded it in the pack's or the paper's `approvals.json`; its note says which pack
or paper and which file.

Do not write, edit or copy `approvals.json`. For a blueprint or a paper, run `next_step.py` on that
paper's folder and carry on with the step it prints, as the make-paper skill says. For a concept
list, carry on as the skill you are following (make-pack or make-paper) says.
