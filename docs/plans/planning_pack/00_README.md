# Agentic RAG Workspace Planning Pack

> **Whole-project context:** For motivation, current implementation, and doc index, read [../../PROJECT_MASTER.md](../../PROJECT_MASTER.md) first. This pack describes **target** architecture and migration from the MVP baseline.

This planning pack converts the current MVP into a concrete product and engineering direction for the next version of the platform.

It is written so a coding agent or engineer can pick it up and plan implementation without reconstructing the project's intent from chat history.

## Files in this pack

### 01_PRODUCT_AND_ARCHITECTURE_MASTER_PLAN.md
The canonical product definition, system goals, constraints, current-state diagnosis, future-state architecture, and target operating model.

### 02_EDITOR_UX_AND_SUGGESTION_SYSTEM.md
The full editor strategy, Word-like UX direction, Tiptap/ProseMirror design, AI interaction model, tracked suggestions model, review behavior, and chat behavior.

### 03_DATA_MODEL_API_AND_WORKFLOWS.md
The proposed data model, backend services, job model, retrieval modes, duplicate-prevention logic, API surface, mission lifecycle, and document/update workflows.

### 04_MIGRATION_ROADMAP_AND_CURSOR_EXECUTION_PLAN.md
A phased migration plan from the current codebase to the target system, including what to stabilize immediately, what to replace, what to keep, acceptance criteria, implementation order, and explicit guidance for Cursor or any coding agent.

## How to use this pack

1. Read `01_PRODUCT_AND_ARCHITECTURE_MASTER_PLAN.md` first.
2. Read `02_EDITOR_UX_AND_SUGGESTION_SYSTEM.md` second.
3. Read `03_DATA_MODEL_API_AND_WORKFLOWS.md` third.
4. Use `04_MIGRATION_ROADMAP_AND_CURSOR_EXECUTION_PLAN.md` as the implementation guide.

## Project baseline this pack assumes

This pack is based on the current uploaded codebase, which currently has:
- FastAPI as the main application server
- a single-page web UI
- SQLite persistence
- mission-scoped storage and indexing
- report types for RMP, Timeline, AAR, and SITREP
- FAISS-backed mission indexes with `by_type/*.json` retrieval artifacts
- pending draft and pending edit review behavior
- full-document structured edit generation as the current update path
- section-aware updates implemented (`src/sections.py`, structured edits + overview telemetry); ProseMirror JSON dual-write is optional via `content_json` on save

## Important interpretation rule

Where this pack describes the future system, treat it as the desired target architecture.
Where it describes the current system, treat it as the baseline from which migration work should begin.

## Primary product sentence

This platform is a mission-scoped, human-in-the-loop RAG workspace for collaborative document creation, combining Word/Docs-style editing with grounded AI suggestions, evidence-aware incremental updates, and formal mission review workflows.
