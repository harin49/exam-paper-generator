# Architecture

How the exam-papers plugin is put together, and the path a paper takes from syllabus to PDFs. Each
part is described in [harness-design.md](harness-design.md).

## Plugin and workspace

The plugin is installed read-only. Everything a teacher makes (syllabus packs, papers, approvals)
lives in their own workspace folder.

```mermaid
flowchart LR
    subgraph Plugin["Plugin (installed, read-only)"]
        SK[Skill: playbook, scripts, formats]
        AG[Agents: writer, blind solver, reviewer]
        CM[Commands: /exam-papers:approve, /exam-papers:decide]
        HK[Hooks: record approvals and decisions, block leaks]
    end
    subgraph WS["Teacher's workspace"]
        SY["syllabi/&lt;pack&gt;/"]
        PA["papers/&lt;task&gt;/"]
    end
    Plugin --> WS
```

## From syllabus to PDFs

Scripts check every step; the teacher passes four gates by typing a command ([teacher gates](harness-design.md#teacher-gates)). The review
part of this flow is drawn in more detail in [review-loop.md](review-loop.md).

```mermaid
flowchart TD
    S[Syllabus .md] --> CL[Draft concept list] --> V1[validate_concepts.py] --> G1{{Gate 1: concept list}}
    G1 --> SP[Teacher's spec] --> V2[validate_paper_spec.py] --> BP[make_blueprint.py] --> G2{{Gate 2: blueprint}}
    G2 --> WR[Writer subagent drafts] --> CK[check_questions.py]
    CK -->|fail| WR
    CK -->|pass| RV[Blind solver + reviewer]
    RV -->|errors, rounds left| WR
    RV -->|warnings, suggestions| G3{{Gate 3: finding decisions}}
    G3 -->|address, rounds left| WR
    RV -->|still open after round 3| G3
    G3 -->|dispute: instruction for one extra round| WR
    G3 -->|dispute: teacher fixes or rejects| G4
    RV -->|nothing open| G4{{Gate 4: final paper}}
    G3 -->|all rejected| G4
    G4 --> R[render.py: PDFs]
```
