# PART C — Data model, services, API, workflows (`03`)

**Source:** [../planning_pack/03_DATA_MODEL_API_AND_WORKFLOWS.md](../planning_pack/03_DATA_MODEL_API_AND_WORKFLOWS.md)

Each subsection: **Pack intent** → **Current MVP (`agentic_rag_mvp`)** → **Delta (by phase)** → **Verification**.

---

## §1 Purpose

- **Pack:** Backend-oriented target platform design.
- **Current:** FastAPI + SQLite + mission reports match the *direction* but not full entity set.
- **Delta:** Migrate incrementally per PART_D; keep seeds listed in §12 below.
- **Verification:** Each phase exit matches `04` §14.

---

## §2 High-level system model

Core entities (pack): MissionWorkspace, MissionMember, SourceDocument, ReportTemplate, Report, ReportSection, ReportRevision, SuggestionJob, Suggestion, Comment, ApprovalAction, AuxiliaryKnowledgeSource.

- **Current:** `missions`, `reports`, `pending_edits`, `pipeline_jobs` (Phase 0), manifest files, FAISS/by_type.
- **Delta:** Add missing tables per §3; generalize `pipeline_jobs` toward full `SuggestionJob` (§3.8).

---

## §3 Proposed data model (field-level)

### §3.1 MissionWorkspace

| Field (pack) | Current | Delta |
|--------------|---------|--------|
| id | `missions.id` | — |
| name | `missions.name` | — |
| status | `missions.status` (subset) | Expand enum: paused, review, complete, archived |
| classification | — | Add column or `settings_json` |
| source_path | `source_path` | — |
| output_path | `output_path` | — |
| ingest_mode | — | Phase 1: `auto` \| `manual` |
| created_at / updated_at | yes | — |
| created_by_user_id / mel_user_id | — | Phase 5 + auth |
| settings_json | partial via flat cols | Optional consolidate |
| mission_metadata_json | partial (cpt, workflow_title, …) | Align naming |

### §3.2 MissionMember

| Field | Current | Delta |
|-------|---------|--------|
| mission_id, user_id, role, permissions_json, timestamps | — | New table Phase 5 |

Roles: operator, crew_lead, mel, viewer.

### §3.3 SourceDocument

| Field | Current | Delta |
|-------|---------|--------|
| id, mission_id, path, display_name, checksum, mtime, doc_type, … | Implicit: filesystem + `manifest.json` | Optional `source_documents` table; ingest_status |

### §3.4 ReportTemplate

| Field | Current | Delta |
|-------|---------|--------|
| template_schema_json, version | [document_templates.py](../../src/templates/document_templates.py) HTML | Phase 1: versioned schema + section keys |

### §3.5 Report

| Field | Current | Delta |
|-------|---------|--------|
| mission_id + report_type | PK on `reports` | Phase 1: status, `current_document_json`, revision pointers, `last_generated_from_job_id`, evidence snapshot id |
| current_document_json | — | Replace HTML SoT in Phase 2+ |
| current_html_cache | `current_content` | Transitional cache from PM/Quill |

### §3.6 ReportSection

| Field | Current | Delta |
|-------|---------|--------|
| section_key, order, policy | — | New table or embedded in template schema Phase 1 |

### §3.7 ReportRevision

| Field | Current | Delta |
|-------|---------|--------|
| revision_number, document_json, source_job_id, … | — | New table Phase 1 |

### §3.8 SuggestionJob

| Field | Current (`pipeline_jobs`) | Delta |
|-------|---------------------------|--------|
| id, mission_id, status, progress_json, error_message, timestamps | yes | Add: `report_id` / report_types (JSON), `job_type`, `scope_type`, `retrieval_mode`, `evidence_snapshot_id`, `created_by_user_id` |
| job_type enum (inline_rewrite, first_draft, …) | `job_kind` partial (`pipeline_all` / `pipeline_partial`) | Expand Phase 1 |

### §3.9 Suggestion

| Field | Current (`pending_edits`) | Delta |
|-------|-------------------------|--------|
| anchor, types, revision binding, duplicate fields | block_id, operation, old/new html | Add `job_id`, `suggestion_type` enum, `created_against_revision_id`, similarity/provenance JSON Phase 1 |

### §3.10 Comment

| Field | Current | Delta |
|-------|---------|--------|
| — | — | Phase 5 |

### §3.11 ApprovalAction

| Field | Current | Delta |
|-------|---------|--------|
| — | — | Phase 5 |

### §3.12 AuxiliaryKnowledgeSource

| Field | Current | Delta |
|-------|---------|--------|
| — | — | Phase 4 + admin |

---

## §4 Service boundaries (4.1–4.7)

| Service | Current mapping | Delta |
|---------|-----------------|--------|
| 4.1 Workspace | `mission_service` | Members, ingest mode, settings |
| 4.2 Document | `report_service` + templates | Revisions, section identity, PM JSON |
| 4.3 Suggestion | `report_service` pending + `pipeline_job_service` | Unified suggestion service |
| 4.4 Retrieval | `retrieve/`, `agents/` | Explicit speed vs coverage APIs Phase 3–4 |
| 4.5 Ingest | `index/build`, `ingest/`, manifest | SourceDocument table, discovery API |
| 4.6 Approval | `report_review_service`, review routes | Phase 5 MVP (status, comments, finalize, audit) |
| 4.7 Export | `html_to_docx` | PM JSON → DOCX path Phase 2 |

---

## §5 Retrieval (5.1–5.4)

- **5.1** Mode split: **Partial** — inline-assist (small k) vs pipeline/coverage path.
- **5.2** Speed: local context + small evidence — **Done** Phase 3 — `inline_assist_service` (k≤4 when index exists).
- **5.3** Coverage: broad recall, dedupe, refs — **Partial** — incremental + coverage job metadata + `filter_near_duplicate_edits`.
- **5.4** Auxiliary: **Gap** Phase 4 (pack auxiliary knowledge store not built).

---

## §6 Duplicate prevention (6.1–6.3)

- **Current:** `filter_near_duplicate_edits` on structured pipeline output; evidence refs backfilled from retrieval when missing.
- **Delta:** Optional stronger fingerprints / UI surfacing of suppressed dupes beyond job events.

---

## §7 Job model (7.1–7.3)

- **7.1** Durable jobs: **Partial** — `pipeline_jobs` + `progress_json` events.
- **7.2** Flow: align UI to poll jobs (Phase 0 UI follow-up).
- **7.3** Progress steps: map event names to pack list (`retrieval_*`, `generation_*`, …); extend as needed.

---

## §8 API surface — pack endpoint → MVP mapping

**Note:** Pack uses `/api/workspaces/...`. MVP uses `/api/missions/...` until PART_F decision to alias or migrate.

### §8.1 Workspace APIs

| Pack endpoint | MVP equivalent / status |
|---------------|-------------------------|
| POST /api/workspaces | POST /api/missions |
| GET /api/workspaces | GET /api/missions |
| GET /api/workspaces/{id} | GET /api/missions/{id} |
| PATCH /api/workspaces/{id} | PATCH /api/missions/{id} |
| POST …/members | **Gap** Phase 5 |
| PATCH …/members/{user_id} | **Gap** Phase 5 |
| PATCH …/settings | PATCH …/metadata (partial) |

### §8.2 Source document APIs

| Pack | MVP |
|------|-----|
| GET …/documents | **Gap** (list files client-side or new route) |
| POST …/discover, ingest, DELETE, reclassify | **Gap** — index build implicit in pipeline |

### §8.3 Report APIs

| Pack | MVP |
|------|-----|
| GET …/reports | GET …/reports/{type} per type (aggregate **Gap**) |
| GET …/reports/{type} | yes |
| PATCH …/reports/{type} | save via POST …/save |
| POST …/initialize | create_mission seeds templates |
| POST …/export/docx | accept/save/apply write docx |
| POST …/export/pdf | **Gap** |

### §8.4 Suggestion APIs

| Pack | MVP |
|------|-----|
| POST …/jobs | **Partial** — pipeline creates job internally; no generic POST jobs yet |
| GET …/jobs/{id} | **Partial** — GET /api/missions/{id}/pipeline-jobs/{job_id} |
| GET …/suggestions | GET …/pending-edits |
| accept/reject / accept-all / reject-all | yes (edits routes) |

### §8.5 Review and approval APIs

| Pack | MVP |
|------|-----|
| submit / approve crew / approve MEL / return | **Partial** — `PATCH …/reports/{type}/review-status` (draft → in_review → crew_lead_approved → mel_approved; reopen final→draft); `POST …/finalize` (mel_approved→final + audit); `GET …/approval-log`; optional `actor_label`. Pack-named role endpoints / members N/A. |

### §8.6 Chat APIs

| Pack | MVP |
|------|-----|
| POST …/chat, create-suggestion | **Gap** Phase 3–4 |

### §8.7 Activity APIs

| Pack | MVP |
|------|-----|
| GET …/activity | **Gap** |
| GET …/jobs | **Partial** — GET …/pipeline-jobs |
| GET …/new-evidence-summary | **Partial** — `GET …/missions/{id}/evidence-delta` (Phase 4 MVP) |

---

## §9 Workflow definitions (step-by-step vs MVP)

### §9.1 Mission initialization

| Step | MVP |
|------|-----|
| 1–3 MEL + metadata + members | Create mission + PATCH metadata; members N/A |
| 4 templates | `create_mission` seeds reports |
| 5 discover/ingest | User runs pipeline / index build |
| 6 Draft | Default |

### §9.2 User editing

| Step | MVP |
|------|-----|
| 1–3 open/edit/save | Quill + POST save |
| 4 revision checkpoint | **Gap** Phase 1 |

### §9.3 Inline AI

| Step | MVP |
|------|-----|
| 1–7 | **Done** Phase 3 — `POST …/inline-assist` + staged apply in editor |

### §9.4 Full-draft generation

| Step | MVP |
|------|-----|
| Explicit job + coverage | **Partial** — fallback full RAG inside structured path |

### §9.5 New-evidence update

| Step | MVP |
|------|-----|
| 1–8 | **Partial** — manifest + `last_used_doc_paths`; evidence-delta overview UI; server-side dedupe on structured edits (`filter_near_duplicate_edits`) |

### §9.6 Chat-assisted

| Step | MVP |
|------|-----|
| 1–5 | **Gap** |

### §9.7 Approval

| Step | MVP |
|------|-----|
| 1–4 | **Partial** — status transitions + finalize + audit log + comments (`GET`/`POST …/comments`); no pack-level member RBAC |

---

## §10 Versioning and invalidation

- **Current:** `pending_edits.created_against_revision_id` populated when suggestions are created (Phase 1).
- **Delta:** Explicit client invalidate-on-anchor-miss UX optional; server validates block ids on apply.

---

## §11 Observability

- **Current:** Logging + `pipeline_jobs.progress_json` + per-report timing events in jobs.
- **Delta:** Instrument ingest, dedupe, apply, export per pack list; optional metrics table.

---

## §12 Seeds in current codebase (pack §12)

- Report persistence, pending edits, retrieval by type, manifest + `last_used_doc_paths`, `pipeline_jobs`.

Preserve and formalize into services/entities per PART_D.
