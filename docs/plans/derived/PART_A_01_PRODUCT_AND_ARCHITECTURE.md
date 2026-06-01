# PART A — Product & architecture (`01`)

**Source:** [../planning_pack/01_PRODUCT_AND_ARCHITECTURE_MASTER_PLAN.md](../planning_pack/01_PRODUCT_AND_ARCHITECTURE_MASTER_PLAN.md)

Template per subsection: **Pack summary** → **Current codebase** → **Delta** → **Risks** → **Verify**.

---

## §1 Executive summary

- **Pack:** Move from report-gen MVP to mission-scoped collaborative document workspace; split inline assist vs grounded jobs.
- **Current:** MVP proves mission RAG + templates + human review; still bulk structured updates + Quill.
- **Delta:** PART_D Phases 0–6.
- **Risks:** Big-bang rewrite — **avoid** (`04` §16).
- **Verify:** Product success `01` §14 when phases complete.

---

## §2 Product definition

### §2.1 Canonical product statement

- **Delta:** Align messaging in README/INDEX with pack sentence when stable.

### §2.2 What the product is

- **Current:** Partial match — mission RAG workspace with four report types.
- **Delta:** Add collaborative editor, explicit roles, suggestion-first AI, evidence UX.

### §2.3 What the product is not

- **Verify:** No silent auto-apply; no cross-mission corpus; document remains center (`04` §15.9).

---

## §3 Core goals

### §3.1 User-facing goals

- **Delta:** Time savings, stress reduction, polished drafting UX, trust, human ownership — measure qualitatively per release.

### §3.2 Technical goals

- **Current:** Mission isolation, templates, local stack — **yes**.
- **Delta:** Dual retrieval modes, duplicate control, fast vs exhaustive paths.

### §3.3 Non-negotiables

- **Verify:** Checklist before each PR: isolation, HITL, templates, on-demand AI, grounded when needed, Word-like target, duplicate-aware updates.

---

## §4 Roles and permissions

### §4.1 Roles

- **Current:** No auth; metadata fields only.
- **Delta:** Phase 5 — Operator, Crew lead, MEL, viewer (`03` §3.2).

### §4.2 Permission direction

- **Delta:** Mission-scoped permissions JSON; enforce on API.

---

## §5 Workspace model

### §5.1 Definition

- **Current:** `missions` row + paths.
- **Delta:** Workspace = mission + settings + permissions + job/suggestion state.

### §5.2 Contents

- **Delta:** Revisions, suggestions, comments, approvals as first-class stores.

### §5.3 Isolation

- **Current:** Per-mission index and DB rows — **good**.
- **Verify:** Any new cache/table includes `mission_id`.

### §5.4 Mission lifecycle

- **Delta:** Automate transitions (archived, review) when product ready.

---

## §6 Report model

### §6.1 Report types RMP, Timeline, AAR, SITREP

- **Current:** `REPORT_TYPES` — **yes**.

### §6.2 Template behavior

- **Current:** Templates on create; AI not auto-first-draft unless user runs update — **roughly aligned**.
- **Delta:** Explicit “generate first draft” job type vs “update evidence”.

### §6.3 Section model

- **Current:** HTML blocks inferred — **weak**.
- **Delta:** Phase 1 explicit section keys in schema.

### §6.4 Draft quality

- **Delta:** Phase 2 page layout + typography.

---

## §7 Current-state diagnosis

### §7.1–7.4

- **Current:** As pack describes — see [PART_E_CODEBASE_CROSSWALK.md](PART_E_CODEBASE_CROSSWALK.md).

### §7.5 Problem 1 — One mechanism doing too much

- **Delta:** Phase 3–4 split inline vs grounded.

### §7.5 Problem 2 — Section-aware not real

- **Delta:** Phase 1 schema + Phase 4 `sections.py`.

### §7.5 Problem 3 — HTML/block not long-term SoT

- **Delta:** Phase 2 PM JSON.

### §7.5 Problem 4 — Not document-native enough

- **Delta:** Phases 2–3 UX + jobs.

### §7.5 Problem 5 — Jobs vs inline shapes differ

- **Delta:** Phase 0 jobs + Phase 3 speed path.

---

## §8 Future-state architecture (layers 8.1–8.7)

Map each layer to services in PART_C §4:

- Workspace, Editor, Suggestion, Retrieval, Update/job, Review, Export — implement across Phases 1–5.

---

## §9 Two-mode AI

### §9.1 Mode A inline

- **Delta:** Phase 3.

### §9.2 Mode B grounded

- **Delta:** Phase 4 jobs + coverage retrieval.

### §9.3 Why split

- **Verify:** Do not route both through identical prompts (`04` §15.6).

---

## §10 Retrieval strategy

### §10.1 Coverage mode

- **Delta:** Phase 4.

### §10.2 Speed mode

- **Delta:** Phase 3 (inline).

### §10.3 Report-specific (Timeline, RMP, SITREP, AAR)

- **Current:** Timeline crew_log only; others multi-type — **partial** alignment.
- **Delta:** Event-level timeline, delta SITREP, auxiliary RMP — Phase 4.

### §10.4 Auxiliary official knowledge

- **Delta:** Phase 4 + `03` §3.12.

---

## §11 Duplicate prevention

- **Current:** None.
- **Delta:** Phase 4 provenance + similarity (PART_C §6).

---

## §12 Review and approval

### §12.1 Suggestion rule

- **Current:** Accept/reject edits — **aligned**.
- **Verify:** No auto-apply on ingest (`02` §13.3).

### §12.2 Role behavior

- **Delta:** Phase 5.

### §12.3 Report status model

- **Delta:** Phase 5 statuses.

---

## §13 Recommended technical decisions

### Keep

- FastAPI, SQLite (for now), mission scope, templates, DOCX, local deploy, report-specific retrieval direction.

### Replace / redesign

- Quill/HTML SoT long-term, monolithic update, stream-only long jobs, stub sections.

### Add

- PM editor, durable suggestions, jobs, sections, duplicate logic, ingest modes, chat→suggestions.

---

## §14 Product success definition

- **Verify:** Use as release checklist before calling migration “done”.

---

## §15 Final architectural thesis

- **Verify:** Document-centric, suggestions first-class, mission-isolated mode-aware retrieval, trust-preserving AI.
