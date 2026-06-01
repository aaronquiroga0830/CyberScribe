# PART F — Decisions, assumptions, appendix (`04` §15–§17 verbatim)

## Open decisions (working assumptions until changed)

| Topic | Assumption | Alternatives |
|-------|------------|----------------|
| API prefix | Extend `/api/missions/...` | Parallel `/api/workspaces/...` |
| Auth | Defer multi-user until Phase 5 scope | Early stub `user_id` on jobs |
| SSE | Keep for streaming chunks; jobs authoritative for status | Replace with job-only + polling |
| DOCX | Keep [html_to_docx.py](../../src/html_to_docx.py) through Phase 2 | Second exporter from PM JSON |

Record **Decided** + date in [PLANNING_PACK_DERIVED_INDEX.md](PLANNING_PACK_DERIVED_INDEX.md) when you choose.

---

## Appendix — `04` §15 Explicit guidance (verbatim)

Use this section as direct working guidance.

### 15.1 Do not optimize the old full-document structured edit flow as the long-term solution

It can be stabilized temporarily, but it is not the intended final interaction model.

### 15.2 Treat the editor replacement as foundational work, not cosmetic work

Do not delay the editor change until the very end.
Many downstream requirements depend on it.

### 15.3 Model suggestions and jobs before building advanced UX polish

Without a durable suggestion/job model, the UI will stay fragile.

### 15.4 Preserve mission isolation everywhere

Any new service, store, or cache must remain mission-scoped by default.

### 15.5 Keep AI proposal-based

Do not introduce any hidden auto-apply behavior.
Humans remain in control.

### 15.6 Keep retrieval mode-aware

Do not force inline assist and grounded updates through identical retrieval or prompt logic.

### 15.7 Build duplicate prevention early enough that update quality improves during migration

Do not postpone duplicate control until after all UI work is done.
It is central to user trust.

### 15.8 Keep DOCX quality visible during migration

Do not let export degrade while the new editor is being built.

### 15.9 Keep the document as the center of gravity

Do not let chat or dashboards become the dominant interface.
The document workspace is the product core.

---

## Appendix — `04` §16 What to avoid (verbatim)

Avoid these traps:

- rebuilding everything at once
- overfitting more engineering into the old editor foundation
- treating chat as a separate product that bypasses suggestion review
- hiding long-running state inside one streaming endpoint
- implementing section updates before explicit section identity exists
- treating top-k retrieval as sufficient for completeness-sensitive document generation

---

## Appendix — `04` §17 Final migration thesis (verbatim)

The migration should produce a system where:

- the editor is document-native
- AI suggestions are first-class, durable, and reviewable
- updates are job-driven and evidence-aware
- retrieval supports both speed and coverage
- new evidence is visible and actionable
- duplicate reintroduction is actively controlled
- the operator, crew lead, and MEL workflow is real in the product

That is the standard the codebase should move toward.
