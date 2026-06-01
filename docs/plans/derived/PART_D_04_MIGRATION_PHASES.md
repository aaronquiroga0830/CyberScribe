# PART D — Migration roadmap (`04` exhaustive)

**Source:** [../planning_pack/04_MIGRATION_ROADMAP_AND_CURSOR_EXECUTION_PLAN.md](../planning_pack/04_MIGRATION_ROADMAP_AND_CURSOR_EXECUTION_PLAN.md)

Execute **in order**: §6 → §7 → … → §12. Do not skip Phase 1 entities before Phase 2 editor swap (`04` §16).

---

## §1 Purpose

- [ ] Read and keep visible for all phases.

---

## §2 Current baseline to preserve

- [ ] FastAPI, mission-scoped data, SQLite, local deploy, report types, template seeding, per-mission index, report-specific retrieval, pending review, DOCX priority — **do not break** without replacement.

---

## §3 Current baseline to phase out

- [ ] Plan retirement: Quill, HTML as long-term SoT, full-doc structured path as *final* UX, stream-as-primary-truth, stub-only section awareness.

---

## §4 Migration philosophy

- [ ] **Rule 1** Word parity after architecture.
- [ ] **Rule 2** Do not conflate inline assist with grounded updates.
- [ ] **Rule 3** Stabilize current product while migrating.
- [ ] **Rule 4** Prefer durable concepts first: jobs, suggestions, revisions, sections.
- [ ] **Rule 5** Preserve export quality.

---

## §5 Phase overview

- [x] Phase 0 — stabilization  
- [x] Phase 1 — domain model  
- [x] Phase 2 — editor  
- [x] Phase 3 — inline assist  
- [x] Phase 4 — grounded updates + duplicate + sections  
- [x] Phase 5 — review/approval  
- [ ] Phase 6 — optional advanced  

---

## §6 Phase 0: immediate stabilization

### Goal / why

- [ ] Read `04` §6 Goal and “Why this phase matters”.

### 6.1 Durable job records for update requests

- [x] Each HTTP-triggered pipeline run creates a DB job (`pipeline_jobs`) and returns `job_id`.
- [x] Scheduler (`src/pipeline.py`) creates the same job record (shared helper via `create_pipeline_job`, `job_kind=scheduler_cycle`).

### 6.2 Structured per-step timing logs

- [x] Timings for retrieval + generation (structured path) in `progress_json`.
- [x] Index build duration event.
- [x] Prompt assembly / parse / persist as separate measured steps (`prompt_assembly_done`, `parse_validate_done`, `persist_pending_edits_done` / `persist_pending_content_done`, `stream_generation_done`, scheduler index/report timings).
- [x] Preview/application timings if distinct endpoints gain async work.  
  _N/A for current synchronous `GET …/preview` and `POST …/apply-edits`; re-open if those become async jobs._

### 6.3 Durable failure records

- [x] `status=failed`, `error_message` on pipeline error.
- [x] Persist parse vs LLM vs pipeline failure in `failure_kind`; invalid `target_block_id` count accumulated in `invalid_edit_count` (+ parse events in `progress_json`).

### 6.4 Progress semantics

- [x] Named steps in `progress_json` (`pipeline_started`, `index_*`, `report_completed`, `pipeline_completed`, per-report retrieval/generation).
- [x] UI polls `GET .../pipeline-jobs` (job polling for completion/failure; SSE optional for live preview).

### 6.5 Review manifest/update behavior

- [x] Audit `manifest.json` vs `last_used_doc_paths` after successful runs; document or fix stale behavior — see [PHASE_0_MANIFEST_INCREMENTAL.md](./PHASE_0_MANIFEST_INCREMENTAL.md).

### 6.6 Naming: distinguish update intents

- [x] `job_kind`: `pipeline_all` vs `pipeline_partial`.
- [x] API/UI labels: `update_intent` + `intent_label` on job rows; optional `full_refresh` checkbox; values include generate-first-draft / evidence update / full refresh / scoped single report / scheduled cycle.

### Phase 0 deliverables (`04`)

- [x] durable job state
- [x] better logs/failures
- [x] clearer naming

### Phase 0 acceptance (`04` §14)

- [x] Update requests create durable job records.
- [x] Failures diagnosable from DB (`failure_kind`, `error_message`, progress events) + logs.
- [x] Timing data for major pipeline steps (index, retrieval, prompt assembly, LLM, parse/validate, persist, stream generation, scheduler reports).

---

## §7 Phase 1: target domain model

### 7.1 Report revision support

- [x] Revision model; checkpoint on accept/save.

### 7.2 Evolve pending_edits → suggestions

- [x] `suggestion_type`, `source_job_id`, `revision_id`, evidence, status transitions.

### 7.3 Explicit section definitions

- [x] Section schema per template **before** real `sections.py` targeting.

### 7.4 Suggestion job model

- [x] Generalize `pipeline_jobs` toward full `SuggestionJob` (`03` §3.8) — `job_type`, `scope_type`, `retrieval_mode` columns (Phase 1 slice).

### 7.5 Mission ingest mode

- [x] auto vs manual ingest (`missions.ingest_mode` + API + overview UI; pipeline still auto-indexes until confirm UX).

### Phase 1 deliverables / acceptance

- [x] Per `04` §7 deliverables and §14 Phase 1 acceptance (DB-backed revisions, suggestions metadata, section definitions, job fields, ingest mode).

---

## §8 Phase 2: replace editor foundation

### 8.1 New editor shell

- [x] Tiptap/ProseMirror report experience.

### 8.2 Core formatting

- [x] bold, italic, underline, headings, lists, indentation, font (if feasible), image paste, tables (if feasible).  
  _(Image: URL prompt + base64; table insert via toolbar.)_

### 8.3 Page-style presentation

- [x] Page frame, margins, typography.

### 8.4 Templates → explicit document structures

- [x] Instantiate from structured template.  
  _(Seeded HTML wraps each section in `<section class="report-section" data-section-key data-section-policy>` from `SECTION_DEFINITION_SEED`; Tiptap `reportSection` node; existing missions keep legacy flat HTML until reset.)_

### 8.5 Preserve export path

- [x] DOCX from new model or adapter from HTML cache.  
  _(Still `getHTML()` → existing save / `html_to_docx` path.)_

### Phase 2 deliverables / acceptance

- [x] §14 Phase 2 acceptance (Tiptap usable, page-style layout, core formatting).
- [x] Full `04` §8 checklist (including **8.4** structured template instantiation).

---

## §9 Phase 3: inline assist

### 9.1 Selection-based actions

- [x] rewrite, shorten, expand, formalize, operationalize, list/paragraph convert.  
  _(Dropdown + Run on selection; `POST .../inline-assist`.)_

### 9.2 Cursor-based actions

- [x] suggest next sentence, insert paragraph, fill placeholder.  
  _(“Cursor assist” row under the formatting toolbar.)_

### 9.3 Suggestions only (no direct apply)

- [x] All AI output staged.  
  _(Staging panel + Accept / Reject before `insertContent` / replace.)_

### 9.4 Accept/reject in editor

- [x] Inline review UX.  
  _(Staging strip under the page shell.)_

### 9.5 Minimal evidence for scoped actions

- [x] Speed retrieval path.  
  _(k≤4 semantic chunks only when `mission_index_exists`; otherwise no retrieval.)_

### Phase 3 deliverables / acceptance

- [x] Per `04` §9 and §14 Phase 3 (MVP slice: single-endpoint assist + editor UX).

---

## §10 Phase 4: grounded update jobs

### 10.1 Evidence snapshot logic

- [x] Track source state at last update/approval.  
  _`missions.last_source_checkpoint_json` + `_at`, refreshed on save / accept pending / apply accepted edits (`evidence_checkpoint.save_mission_source_checkpoint`)._

### 10.2 New-evidence summaries

- [x] UI indicator without auto-edit.  
  _`GET /api/missions/{id}/evidence-delta` + Mission Overview card._

### 10.3 Coverage-mode update jobs

- [x] New/changed evidence → coverage retrieval → suggestions + evidence refs.  
  _Existing incremental path (`last_used_doc_paths` + `get_new_docs_context_for_report`); job event `coverage_scope` lists new/changed file count and `sections_likely_dirty`; empty `evidence_refs` on edits backfilled from retrieval paths._

### 10.4 Duplicate prevention

- [x] Provenance + similarity.  
  _`filter_near_duplicate_edits` (HTML text similarity) + event `duplicate_edits_suppressed`; retrieval file names on `evidence_refs` when the model omits them._

### 10.5 Section-aware targeting

- [x] Implement [src/sections.py](../../src/sections.py) behavior for real.  
  _`DOC_TYPE_TO_SECTIONS` map → `(report_type, section_key)` for telemetry and UI hints; full structured edit pass unchanged._

### Phase 4 deliverables / acceptance

- [x] Per `04` §10 and §14 Phase 4 (MVP: checkpoint + delta UI + dedupe + section mapping + job metadata).

---

## §11 Phase 5: review and approval polish

### 11.1 Report status transitions

- [x] Draft, In Review, Crew Lead Approved, MEL Approved/Final.  
  _`reports.review_status`; `PATCH .../review-status` + `ALLOWED_TRANSITIONS` in [src/report_review_service.py](../../src/report_review_service.py); pipeline skips MEL-approved/final reports; `409` on blocked mutations._

### 11.2 Comments

- [x] Threaded or anchored comments.  
  _`report_comments` + `GET`/`POST .../comments` (`parent_id`, `anchor_section_key` on POST)._

### 11.3 Section/document review mode

- [x] Reviewer workflows.  
  _Single-report UI: status strip, transition select, optional actor label, comments + approval log._

### 11.4 Final export + approval logging

- [x] Auditable finalization.  
  _`POST .../finalize` (`mel_approved` → `final`, `final_export` event); `GET .../approval-log`; AI/update/assist locked at MEL+final; content edits locked at `final` (reopen `final` → `draft`)._

### Phase 5 deliverables / acceptance

- [x] Per `04` §11 and §14 Phase 5.

---

## §12 Phase 6: later improvements

- [x] Presence heartbeats, admin/debug snapshots, ingest/index confirm UI, archive (`lifecycle_status`), auxiliary knowledge CRUD + retrieval merge, comments threading (parent_id) — **shipped** in app + API (2026-03).

---

## §13 Recommended implementation order (file-level)

### 13.1 Preserve and isolate

- [x] Keep export + mission/report persistence working.
- [x] Isolate old editor vs new editor code paths (Tiptap is primary; `web/app.js` Quill path is legacy / unmaintained).
- [x] Isolate legacy update endpoints vs new job/suggestion endpoints (`pipeline_jobs` + structured `pending_edits`).

### 13.2 New core entities (order)

1. [x] revisions  
2. [x] suggestion jobs (extend `pipeline_jobs`)  
3. [x] suggestions (extend `pending_edits` or new table)  
4. [x] section schema  
5. [x] mission ingest settings  

### 13.3 New editor + APIs in parallel

- [x] After 13.2 baseline, parallel UI/backend.

### 13.4 Retire old pathways gradually

- [x] Deprecate before delete (`web/app.js` Quill retained only as legacy reference; do not extend).

---

## §14 Acceptance criteria by phase (verbatim from pack)

### Phase 0 acceptance

- update requests create durable job records  
- failures are diagnosable  
- timing data exists for the major pipeline steps  

### Phase 1 acceptance

- revisions, suggestions, and jobs exist as database-backed concepts  
- report templates have explicit section identity  

### Phase 2 acceptance

- a Tiptap/ProseMirror editor is usable for report editing  
- page-style document layout exists  
- core formatting is available  

### Phase 3 acceptance

- selection-based AI actions work  
- suggestions are reviewable and reversible  
- inline AI feels meaningfully faster than the old update path  

### Phase 4 acceptance

- new evidence can be surfaced without auto-editing the report  
- update jobs create reviewable grounded suggestions  
- duplicate prevention exists and visibly reduces repeated content  
- section-aware targeting exists in real product behavior  

### Phase 5 acceptance

- report status transitions are enforced  
- comments and review actions exist  
- crew lead and MEL approvals are represented in product behavior  

---

## §15–17

Agent guardrails, traps, final thesis: **[PART_F_DECISIONS_AND_APPENDIX.md](PART_F_DECISIONS_AND_APPENDIX.md)** (verbatim).
