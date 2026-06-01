# PART E — Codebase cross-walk

## Core server & orchestration

| Area | Path | Role |
|------|------|------|
| FastAPI app, REST, SSE, pipeline thread | [server.py](../../server.py) | `request_mission_update`, `_run_pipeline`, `_run_structured_edits`, API routes |
| Mission CRUD | [src/mission_service.py](../../src/mission_service.py) | |
| Reports, pending, edits, docx | [src/report_service.py](../../src/report_service.py) | |
| SQLite init | [src/db/models.py](../../src/db/models.py) | `init_db`, `REPORT_TYPES`; Phase 1: `report_revisions`, `report_section_definitions`, `pending_edits` suggestion cols, `pipeline_jobs` job_type/scope, `ingest_mode`; Phase 5: `review_status`, `report_comments`, `report_approval_events` |
| Revisions (Phase 1) | [src/revision_service.py](../../src/revision_service.py) | Checkpoints on accept / save / apply-edits |
| Section defs (Phase 1) | [src/section_definitions.py](../../src/section_definitions.py) | Seed + `list_section_definitions_for_report_type` |
| Pipeline jobs (Phase 0+) | [src/pipeline_job_service.py](../../src/pipeline_job_service.py) | Durable jobs + Phase 1 `job_type` / `scope_type` |
| Index build | [src/index/build.py](../../src/index/build.py) | `mission_index_exists`, `build_mission_index`, manifest |
| Retriever | [src/retrieve/retriever.py](../../src/retrieve/retriever.py) | `get_mission_retriever`, `get_new_docs_context_for_report` |
| Scheduler path | [src/pipeline.py](../../src/pipeline.py) | `run_mission_cycle` — RMP+Timeline only, full rebuild, `set_pending` |
| Scheduler entry | [run_scheduler.py](../../run_scheduler.py) | |
| CLI | [run.py](../../run.py) | build/run/all |
| SPA | [web/app.ts](../../web/app.ts), [web/tiptap-editor.ts](../../web/tiptap-editor.ts), [web/report-section-extension.ts](../../web/report-section-extension.ts) | Tiptap + §8.4 sections + §9 inline assist UI |
| Inline assist API | [server.py](../../server.py), [src/inline_assist_service.py](../../src/inline_assist_service.py), [src/templates/inline_assist_prompts.py](../../src/templates/inline_assist_prompts.py) | `POST .../inline-assist` |
| Phase 4 evidence / sections | [src/evidence_checkpoint.py](../../src/evidence_checkpoint.py), [src/sections.py](../../src/sections.py), [src/edit_dedupe.py](../../src/edit_dedupe.py), [src/ingest/manifest.py](../../src/ingest/manifest.py) | Checkpoint on save/accept/apply; `GET .../evidence-delta`; job `coverage_scope` + dedupe |
| Phase 5 review / approval | [src/report_review_service.py](../../src/report_review_service.py), [server.py](../../server.py) (`review-status`, comments, approval-log, finalize; `409` locks), [web/app.ts](../../web/app.ts) | Status workflow, audit log, pipeline skip for locked reports |

## Dual pipeline (historical differences)

| Aspect | UI / `server.py` | Scheduler / `run.py` + `pipeline.py` |
|--------|------------------|--------------------------------------|
| Report types | Four (`rmp`, `timeline`, `aar`, `sitrep`), structured edits | **RMP + Timeline only** |
| Index | Skip if `mission_index_exists` | **Always** `build_mission_index` |
| Persistence | `set_pending_edits` / `set_pending` | `set_pending` for rmp/timeline |
| Jobs | `pipeline_jobs` from `_run_pipeline` | Same table via `create_pipeline_job` in `run_mission_cycle` (Phase 0) |

**Done (Phase 0):** `run_mission_cycle` creates `pipeline_jobs` via `create_pipeline_job` (`job_kind=scheduler_cycle`, `update_intent=scheduled_cycle`) and records index/report timing events.

## Recommended file touch order (from `04` §13.2)

When implementing **Phase 1** entities, expect to touch primarily:

1. [src/db/models.py](../../src/db/models.py) — new tables / migrations
2. [src/mission_service.py](../../src/mission_service.py) / new `workspace_service` — optional split
3. [src/report_service.py](../../src/report_service.py) — revisions, suggestions evolution
4. [src/pipeline_job_service.py](../../src/pipeline_job_service.py) — generalize jobs
5. [server.py](../../server.py) — new routes; keep mission isolation on queries
6. [web/app.ts](../../web/app.ts) — after backend entities stable (`04` §13.3)

## Docs

- [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md)
- [PROJECT_DEEP_SUMMARY.md](../../PROJECT_DEEP_SUMMARY.md)
