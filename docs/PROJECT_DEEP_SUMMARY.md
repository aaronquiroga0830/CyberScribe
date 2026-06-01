# Agentic RAG MVP — exhaustive project summary

> **Superseded as the read-first doc:** Use [PROJECT_MASTER.md](PROJECT_MASTER.md) for the full picture (motivation, product, technical, roadmap). This file remains for focused reference.

**Purpose:** Single in-depth reference for humans and LLMs. For day-to-day conventions and file roles, [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) remains the maintained source of truth; this document expands architecture, dual pipelines, APIs, and implementation detail in one place.

**Last updated:** 2026-03-23 (reflects codebase at time of authoring).

---

## 1. What this project is

- **Name:** Agentic RAG MVP (Mission RAG).
- **Goal:** Mission-isolated, locally hosted RAG for CPT/mission documents. Users define a **mission name**, **source path** (document pick-up), and **output path** (drop-off for approved reports). The system ingests supported files, builds a **per-mission** vector index and chunk store, and assists generation of **RMP (Risk Mitigation Plan)**, **Mission Timeline**, **AAR**, and **SITREP** as HTML drafts with **human-in-the-loop** review (accept/reject edits, direct editing, `.docx` export).
- **“Agentic”:** Specialized generation paths (RMP, Timeline, etc.) with distinct prompts and retrieval. **Orchestration is deterministic Python** in `server.py` and `src/pipeline.py` — there is **no** LLM “router” that decides which agent runs.
- **UI:** One **Liquid Glass** SPA served by FastAPI. Streamlit was removed; there is no `app.py` streaming UI.

---

## 2. Critical distinction: two execution paths

Understanding this avoids confusion when reading logs or scheduler behavior.

| Aspect | **FastAPI / UI path** | **Scheduler / CLI path** |
|--------|------------------------|---------------------------|
| **Entry** | `request_mission_update` → `_run_pipeline` in `server.py` | `run_mission_cycle` in `src/pipeline.py`; `run.py`; `run_scheduler.py` |
| **Report types** | All four: `rmp`, `timeline`, `aar`, `sitrep` | **RMP and Timeline only** |
| **Index** | Rebuild only if `mission_index_exists` is false; otherwise skip | **Always** full `build_mission_index` in `run_mission_cycle` |
| **Generation mode** | Structured JSON **block-level edits** for all four types; fallback full-draft RAG + synthetic edit; incremental context when `last_used_doc_paths` is set | Template-as-query RAG via `run_template_rag_agent`; `set_pending` for rmp/timeline in DB |
| **Text file output** | Not the primary artifact; DB + UI; `.docx` on accept/save/apply | `run_all_report_agents` writes `output/<mission_id>/rmp_draft.txt`, `timeline_draft.txt` |

The **UI** path is the full product surface (four reports, structured edits, preview, SSE). The **scheduler/CLI** path matches an older “ingest + RMP + Timeline pending” loop and does **not** mirror the four-type structured-edit pipeline.

---

## 3. High-level architecture

```
Browser (http://localhost:8000)
  → web/index.html + app.js + styles.css (hash-routed SPA)
  → FastAPI (server.py)
       REST /api/...
       SSE /api/stream/{mission_id}/{report_type}
       Static + SPA fallback for web/
  → Background thread: _run_pipeline
       optional build_mission_index
       _run_structured_edits per report type (or legacy stream path)
  → src/: mission_service, report_service, index, retrieve, agents, templates, ingest, utils, …
  → SQLite data/agentic_rag.db
  → data/indexes/<mission_id>/ (by_type/*.json, faiss/ or chroma/)
  → output_path: .docx on accept / save / apply_accepted_edits
```

---

## 4. Stack and dependencies

| Layer | Technology |
|-------|------------|
| Server | FastAPI, uvicorn |
| Front-end | `web/app.ts` → `web/app.js` (`npm run build`, TypeScript 5.x); `styles.css` |
| RAG | LangChain (loaders, splitter, retrievers, prompts, ChatOllama, chains) |
| Vector store | FAISS default; optional Chroma (`VECTOR_STORE_TYPE=chroma`) |
| Embeddings | sentence-transformers default `all-MiniLM-L6-v2`; configurable provider/model |
| LLM | Ollama; default `phi3` |
| DB | SQLite `data/agentic_rag.db` |
| Scheduler | APScheduler, default daily **02:00** |
| Report files | `python-docx` via `html_to_docx.py` |

**Python:** `requirements.txt` (langchain, langchain-community, faiss-cpu, sentence-transformers, pypdf, python-docx, apscheduler, fastapi, uvicorn, python-dotenv, requests). Optional: chromadb, unstructured for richer .docx loading.

**Node:** dev-only; `package.json` runs `tsc` to compile the SPA.

---

## 5. Configuration (`config/settings.py`)

Environment variables (via `.env` / `python-dotenv`):

- `OLLAMA_BASE_URL` — default `http://localhost:11434`
- `OLLAMA_MODEL` — default `phi3`
- `OLLAMA_BASE_URL_RMP`, `OLLAMA_BASE_URL_TIMELINE` — optional per-report Ollama instances for parallelism
- `get_ollama_base_url_for_report(report_type)` selects the URL
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`
- `VECTOR_STORE_TYPE` — `faiss` or `chroma`
- `DATA_DIR`, `MISSIONS_DIR`, `INDEX_DIR`, `OUTPUT_DIR` — under project root with defaults

**Parallel inference:** See `README.md`: set `OLLAMA_NUM_PARALLEL=2` before starting Ollama, or run a second Ollama (e.g. port 11435) and set `OLLAMA_BASE_URL_TIMELINE`.

---

## 6. Repository layout (important paths)

### Root

| Path | Role |
|------|------|
| `server.py` | FastAPI app, REST, SSE, `_run_pipeline`, `_run_structured_edits`, static/SPA |
| `run.py` | CLI: `build`, `run`, `all` |
| `run_scheduler.py` | Daily scheduler process |
| `requirements.txt`, `package.json`, `tsconfig.json` | Dependencies and TS build |
| `.gitignore` | venv, `.env`, `data/indexes/`, db, `output/`, etc. |
| `README.md` | Setup, run, parallel Ollama notes |

### `config/`

- `settings.py` — env-driven paths and Ollama/embedding settings

### `src/`

| Path | Role |
|------|------|
| `db/models.py` | `REPORT_TYPES`, `_slug`, `init_db`, schema |
| `mission_service.py` | CRUD missions, metadata, ingest/generated timestamps, template seeding |
| `report_service.py` | Pending content/edits, accept/reject/save, preview, apply_edits, `.docx` paths |
| `pipeline.py` | Scheduler-oriented `run_mission_cycle` / `run_all_active_missions` |
| `scheduler.py` | APScheduler wiring |
| `agents/base.py` | `run_template_rag_agent`, `run_template_rag_agent_stream` |
| `agents/report_agents.py` | RMP/Timeline agents; `run_all_report_agents` → `.txt` under `output/` |
| `index/build.py` | `mission_index_exists`, `build_mission_index`, `by_type` JSON, manifest write |
| `index/vectorstore.py` | FAISS/Chroma, embeddings |
| `retrieve/retriever.py` | `FixedListRetriever`, `get_mission_retriever`, `get_new_docs_context_for_report` |
| `ingest/loaders.py` | File types, `infer_doc_type`, `load_mission_documents` |
| `ingest/chunking.py` | `RecursiveCharacterTextSplitter`, defaults 1000 / 200 |
| `ingest/manifest.py` | `manifest.json`, `new_or_changed_files` for incremental updates |
| `ingest/daily.py` | `run_daily_ingestion` |
| `templates/prompts.py` | Template queries, generation prompts, structured-edit prompts |
| `templates/document_templates.py` | HTML skeletons per report type |
| `document_blocks.py` | Parse/apply block-level HTML edits |
| `merge_draft.py` | Merge LLM output into current draft |
| `html_to_docx.py` | HTML → `.docx` |
| `utils/context_cleaner.py` | Sanitize retrieved context |
| `sections.py` | Design stub; `sections_to_update` returns `[]` |

### `web/`

- `index.html`, `app.ts` / `app.js`, `styles.css` — SPA

### `scripts/`

- `clear_mission_reports.py` — reset mission reports to templates (CLI)

### `data/`

- `agentic_rag.db` — SQLite
- `indexes/<mission_id>/` — index artifacts + `by_type/*.json` + optional `manifest.json`
- `missions/` — optional sample mission folders

### `docs/`

- `PROJECT_CONTEXT.md` — canonical project map
- `solution_workflow_visual_spec.md` — diagram spec for workflow visuals
- This file — consolidated deep summary

---

## 7. Data model (SQLite)

### `missions`

- Core: `id`, `name`, `source_path`, `output_path`, `status`, `created_at`, `updated_at`, `last_ingest_at`, `last_generated_at`
- Optional metadata: `cpt`, `workflow_title`, `start_date`, `end_date`, `operators` (JSON), `mel`, `ccl_host`, `ccl_network`, `auto_update_frequency` (`off` | `hourly` | `6h` | `daily`)

### `reports`

- PK: `(mission_id, report_type)`
- `current_content`, `pending_content`, `pending_at`, `pending_sources`, `current_updated_at`, `last_used_doc_paths`

### `pending_edits`

- Block-level proposals: `edit_id`, `section_id`, `target_block_id`, `operation`, `reason`, `evidence_refs`, `old_html`, `new_html`, `status`, `ord`

**Mission IDs:** Derived from mission name via `_slug` (lowercase alphanumerics + underscores); collision edge case uses short UUID.

---

## 8. Ingestion, typing, and indexing

- **Supported formats:** `.txt`, `.pdf`, `.docx` (richer .docx loading with optional `unstructured`).
- **Document type inference (`infer_doc_type`):** path/filename hints → `crew_log`, `findings`, or `other`.
- **Chunking:** Default chunk size **1000**, overlap **200**.
- **`build_mission_index`:** Loads all mission docs, chunks, writes `by_type/{crew_log,findings,other}.json`, builds FAISS/Chroma, writes **`manifest.json`** (per-file path, `doc_type`, `mtime`) for incremental diffing.
- **`mission_index_exists`:** Requires populated `by_type/*.json` **and** vector store artifacts (FAISS files or Chroma directory per `VECTOR_STORE_TYPE`).

---

## 9. Retrieval

Defined in `src/retrieve/retriever.py`:

- **`REPORT_DOC_TYPES`:**  
  - `timeline` → `crew_log` only  
  - `rmp`, `aar`, `sitrep` → `crew_log` + `findings` + `other`
- **`FixedListRetriever`:** Returns all chunks for those types (query ignored) when `by_type` JSON exists.
- **Fallback:** Semantic `FAISS.as_retriever(k=8)` when by-type store is missing.
- **`get_new_docs_context_for_report`:** Uses `new_or_changed_files` from manifest vs directory scan; loads and chunks only new/changed files matching the report’s doc types; returns concatenated text and paths. Used in `_run_structured_edits` when `last_used_doc_paths` is already set (incremental update narrative).

---

## 10. LLM and prompts

- **Base:** `run_template_rag_agent` / `_stream` — template-as-query retrieval, `clean_context_for_llm`, ChatOllama chain, returns content + source documents for UI traceability.
- **Structured edits:** Separate prompts per report type; LLM returns **JSON array** of edits (with optional markdown code fences stripped). Fields include `target_block_id`, `operation`, `new_html`, `reason`, evidence keys, etc. Invalid or unknown block IDs filtered; empty result triggers **fallback**: full RAG draft, `merge_llm_into_draft`, `set_pending`, plus a **synthetic** pending edit so the UI panel and preview still work.
- **Templates:** `document_templates.py` seeds `current_content` for new missions and supports reset-to-skeleton.

---

## 11. Server orchestration (`server.py`)

### Constants

- `REPORT_SPECS` — `(report_type, template_query, generation_prompt)` for all four types
- `STRUCTURED_EDIT_SPECS` — structured-edit prompt pairs
- `USE_STRUCTURED_EDITS_FOR` — all four report types
- `REPORT_DEPENDENCIES` — e.g. RMP depends on `timeline` for ordering and future content injection
- `_report_run_order` — topological sort so dependencies run first

### Pipeline behavior

1. Sets `running_mission_id`; clears relevant `stream_buffers` entries.
2. If index missing → `build_mission_index` + `update_mission_last_ingest`; else log skip.
3. For each report in ordered list: starts `_run_structured_edits` in a thread (current default for all four types).
4. Queue consumer:  
   - `"edits"` → `set_pending_edits`, mark complete, notify SSE listeners  
   - `"chunk"` / `"sources"` → legacy streaming + `set_pending` path for types not using structured edits  
5. On completion: `update_mission_last_generated` when all reports finish; clears `running_mission_id`.

### Structured-edit thread summary

- Resolves context: full retriever vs incremental `get_new_docs_context_for_report`.
- Parses `current_content` to blocks; builds block ID list for validation.
- Invokes LLM with `temperature=0.2` (structured path).
- On success: persists `set_report_docs_used` with paths touched.
- Puts `(report_type, "edits", list)` on shared queue.

---

## 12. REST API (summary)

Base prefix: `/api`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/missions` | List missions |
| GET | `/missions/{id}` | Get mission |
| POST | `/missions` | Create mission (+ optional metadata fields) |
| PATCH | `/missions/{id}` | Update status |
| PATCH | `/missions/{id}/metadata` | Update workflow metadata |
| GET | `/missions/{id}/reports/{type}` | Get report row |
| GET | `.../preview` | Preview HTML with pending edits applied |
| GET | `.../blocks` | Block list for highlighting |
| POST | `.../accept` | Accept legacy pending content → `.docx` |
| POST | `.../reject` | Reject pending |
| POST | `.../reset` | Reset single report to template |
| POST | `.../save` | Save user HTML (+ optional margins) → `.docx` |
| GET | `.../pending-edits` | List structured edits |
| POST | `.../edits/{edit_id}/accept` | Accept one edit |
| POST | `.../edits/{edit_id}/reject` | Reject one |
| POST | `.../accept-all-edits` | Accept all |
| POST | `.../reject-all-edits` | Reject all |
| POST | `.../apply-edits` | Apply accepted edits to `current_content` + `.docx` |
| POST | `.../update` | Run pipeline for one report type |
| POST | `/run-pipeline` | Run pipeline for all report types |
| GET | `/status` | `{ "running_mission_id": ... }` |

**SSE:** `GET /api/stream/{mission_id}/{report_type}` — replay buffer, stream chunks, periodic ping, `done` sentinel.

**CORS:** Permissive (`*`) for local dev.

---

## 13. Report output filenames

From `report_service` conventions:

- `rmp` → `Risk_Mitigation_Plan.docx`
- `timeline` → `Mission_Timeline.docx`
- `aar` → `After_Action_Report.docx`
- `sitrep` → `SITREP.docx`

---

## 14. Front-end (`web/app.ts`)

- **Routing:** Hash-based: `#/`, `#/new`, `#/mission/<id>/overview`, `#/mission/<id>/<report_type>`, `#/mission/<id>/documents`
- **Features:** Mission list, create mission, overview, per-report Quill editor, proposed-changes panel, preview with highlights, Update / Reset (with confirmation), SSE stream connection, sidebar status polling, client-side timeout handling for long updates (see PROJECT_CONTEXT for UX details)
- **Build:** Edit `app.ts`, run `npm run build`; server serves `app.js`

---

## 15. Key product conventions

- No Streamlit; single FastAPI + static SPA.
- No autonomous LLM orchestrator; Python controls which reports run and in what order.
- **Stream buffers cleared** at pipeline start for affected reports to avoid stale SSE content.
- **Sources** are for reviewer UI; not treated as mandatory footnotes in delivered `.docx` (see PROJECT_CONTEXT).
- **Single-report Reset** vs **mission-wide** template reset (`reset_mission_reports_to_templates` / script) are different operations.
- **TypeScript source of truth:** `web/app.ts`, not hand-editing `app.js`.

---

## 16. How to run

- **Web:** `uvicorn server:app --host 0.0.0.0 --port 8000` → http://localhost:8000
- **Scheduler:** `python run_scheduler.py` (separate long-lived process)
- **CLI:** `python run.py build|run|all <mission_id> [--source PATH] [--sequential]`
- **Utility:** `python scripts/clear_mission_reports.py [mission_id]`

---

## 17. Adding a new report type

1. Add template query, generation prompt, and structured-edit prompt in `src/templates/prompts.py`.
2. Add HTML template in `src/templates/document_templates.py`.
3. Add type to `REPORT_TYPES` in `src/db/models.py` and ensure `create_mission` inserts a row.
4. Wire `REPORT_SPECS`, `STRUCTURED_EDIT_SPECS`, `USE_STRUCTURED_EDITS_FOR` (if applicable), and any dependencies in `server.py`.
5. Extend `REPORT_DOC_TYPES` in `retrieve/retriever.py` if retrieval rules differ.
6. Update `web/app.ts` labels, routes, and API usage.
7. Add `.docx` filename mapping in `report_service` if needed.

---

## 18. Related documentation

- **[PROJECT_MASTER.md](PROJECT_MASTER.md)** — read-first overview (motivation, product, technical, roadmap)
- **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** — authoritative file-by-file map and flows
- **[solution_workflow_visual_spec.md](solution_workflow_visual_spec.md)** — visual workflow diagram requirements (Input → Normalization → Vector store ← Templates → RAG → Backend → Front-end ↔ User ↔ Output)
- **[README.md](../README.md)** — install, Ollama, parallel generation, quick start

---

## 19. Future / stubs

- **Chroma:** Optional; enables different persistence story; incremental add not fully productized in same way as FAISS path.
- **`sections.py`:** Section-aware partial updates not implemented (`sections_to_update` returns empty).
- **Orchestrator:** PROJECT_CONTEXT describes a future LLM orchestrator that could call the same HTTP/update contracts; `REPORT_DEPENDENCIES` anticipates passing dependent report HTML into downstream generators.

---

*End of PROJECT_DEEP_SUMMARY.md.*
