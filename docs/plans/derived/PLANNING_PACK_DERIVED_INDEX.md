# Planning pack — derived implementation index

**Purpose:** Entrypoint for the **exhaustive** plan bundle derived from [../planning_pack/](../planning_pack/). One roadmap split across files for Cursor-sized context.

**Workflow (from project plan):** planning pack → this bundle → **your approval** → phased code execution (`PART_D` order).  
**Do not edit** the Cursor plan file in `.cursor/plans/` unless you intend to change the meta-workflow.

## Pack `00_README` baseline (interpretation rule)

- **Target vs current:** Where the pack describes the **future** system, that is the desired architecture; where it describes the **current** MVP, that is the baseline for migration ([00_README.md](../planning_pack/00_README.md) “Important interpretation rule”).
- **Primary product sentence:** Mission-scoped, human-in-the-loop RAG **workspace** for collaborative document creation — Word/Docs-style editing, grounded AI suggestions, evidence-aware incremental updates, formal mission review workflows ([00_README.md](../planning_pack/00_README.md)).
- **Reading order for humans reading raw pack:** 01 → 02 → 03 → 04 ([00_README.md](../planning_pack/00_README.md)).

## Canonical sources

| Pack file | Role |
|-----------|------|
| [planning_pack/00_README.md](../planning_pack/00_README.md) | Pack index |
| [planning_pack/01_…MASTER_PLAN.md](../planning_pack/01_PRODUCT_AND_ARCHITECTURE_MASTER_PLAN.md) | Product & architecture |
| [planning_pack/02_…SUGGESTION_SYSTEM.md](../planning_pack/02_EDITOR_UX_AND_SUGGESTION_SYSTEM.md) | Editor & UX |
| [planning_pack/03_…WORKFLOWS.md](../planning_pack/03_DATA_MODEL_API_AND_WORKFLOWS.md) | Data model & API |
| [planning_pack/04_…EXECUTION_PLAN.md](../planning_pack/04_MIGRATION_ROADMAP_AND_CURSOR_EXECUTION_PLAN.md) | Phases & acceptance |

## Derived bundle files (required)

| File | Role |
|------|------|
| [PLANNING_PACK_TRACEABILITY.md](PLANNING_PACK_TRACEABILITY.md) | REQ IDs → pack section → phase → PART (Pass D audit) |
| [PART_A_01_PRODUCT_AND_ARCHITECTURE.md](PART_A_01_PRODUCT_AND_ARCHITECTURE.md) | `01` §1–§15 with codebase delta |
| [PART_B_02_EDITOR_UX.md](PART_B_02_EDITOR_UX.md) | `02` §1–§15 |
| [PART_C_03_DATA_MODEL_API_WORKFLOWS.md](PART_C_03_DATA_MODEL_API_WORKFLOWS.md) | `03` §1–§12: entities, services, APIs, workflows |
| [PART_D_04_MIGRATION_PHASES.md](PART_D_04_MIGRATION_PHASES.md) | `04` §1–§14 checklists + acceptance |
| [PART_E_CODEBASE_CROSSWALK.md](PART_E_CODEBASE_CROSSWALK.md) | File map, dual pipeline, touch order |
| [PART_F_DECISIONS_AND_APPENDIX.md](PART_F_DECISIONS_AND_APPENDIX.md) | Decisions + **`04` §15–§17 verbatim** |

## Reading order

1. This INDEX  
2. [PLANNING_PACK_TRACEABILITY.md](PLANNING_PACK_TRACEABILITY.md) (skim REQ IDs)  
3. [PART_E_CODEBASE_CROSSWALK.md](PART_E_CODEBASE_CROSSWALK.md)  
4. [PART_D_04_MIGRATION_PHASES.md](PART_D_04_MIGRATION_PHASES.md) — **implementation sequence**  
5. [PART_C…](PART_C_03_DATA_MODEL_API_WORKFLOWS.md) when changing schema/APIs  
6. [PART_B…](PART_B_02_EDITOR_UX.md) when changing `web/`  
7. [PART_A…](PART_A_01_PRODUCT_AND_ARCHITECTURE.md) for product alignment  
8. [PART_F…](PART_F_DECISIONS_AND_APPENDIX.md) for guardrails  

## Pass D (coverage audit)

Before closing a migration **phase**, confirm every REQ row for that phase in [PLANNING_PACK_TRACEABILITY.md](PLANNING_PACK_TRACEABILITY.md) has either:

- a **Status** (e.g. Done), or  
- an explicit **defer** note in [PART_F_DECISIONS_AND_APPENDIX.md](PART_F_DECISIONS_AND_APPENDIX.md).

## How to run implementation in Cursor

- Use **one phase from PART_D per session** (or smaller chunks inside §6–§12).  
- Attach `@docs/plans/derived/PART_D_04_MIGRATION_PHASES.md` (current section) + `@docs/plans/derived/PART_E_CODEBASE_CROSSWALK.md`.  
- Add PART_C / PART_B / PART_F as needed.  
- Do **not** implement PART_A through F in a single prompt.

## Approval checklist (bundle + execution gate)

**Bundle completeness (agent-verifiable)**

- [x] All required files exist under `docs/plans/derived/`.
- [x] TRACEABILITY lists REQ rows for `00`–`04` outline (expand rows as work splits).
- [x] PART_C includes §3.1–3.12 field tables and §8.1–8.7 endpoint mapping.
- [x] PART_D lists every Phase 0–6 task from `04` §6–§12 as checkboxes + §14 acceptance.
- [x] PART_E documents UI vs scheduler pipeline split.
- [x] PART_F includes verbatim `04` §15–§17.

**Human sign-off (you)**

- [ ] I have read INDEX + PART_D Phase 0 and accept proceeding with code changes per phase.
- [ ] I accept API strategy recorded in PART_F (or I edited PART_F with my decision).

**Execution**

- [x] Phase 0 complete (see PART_D §6 / §14): scheduler `pipeline_jobs`, UI poll + SSE preview, `failure_kind` / `invalid_edit_count` / parse events, `update_intent` + labels, extra timing steps, [PHASE_0_MANIFEST_INCREMENTAL.md](./PHASE_0_MANIFEST_INCREMENTAL.md).
- [x] Phase 1 complete — see PART_D §7 and implementation log.
- [ ] Phase 2+ — per PART_D §8.

## Implementation log

| Date | Phase / scope | Notes |
|------|----------------|-------|
| 2026-03-23 | Bundle | Exhaustive PART_A–F + TRACEABILITY per workflow spec |
| 2026-03-23 | Phase 0 (code, partial) | `pipeline_jobs`, job lifecycle, GET pipeline-jobs, `job_id` on POST run/update |
| 2026-03-23 | Phase 0 (complete) | Scheduler jobs, UI polls `/pipeline-jobs`, `failure_kind` + `update_intent`, structured/stream persist + parse timing, manifest audit doc |
| 2026-03-23 | Phase 1 (complete) | `report_revisions`, suggestion columns + job binding, `report_section_definitions` seed, `pipeline_jobs` job_type/scope_type, `ingest_mode`, revision + section APIs |
