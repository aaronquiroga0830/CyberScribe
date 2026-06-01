# Migration Roadmap and Cursor Execution Plan

## 1. Purpose of this document

This document translates the target product into a phased, executable migration plan.
It is written to help an engineer or coding agent work from the current uploaded codebase without losing sight of the intended end-state.

This is not a rewrite-everything-first plan.
It is an ordered migration plan that stabilizes the current product, replaces the weakest foundations, and preserves what is still useful.

---

## 2. Current baseline to preserve

The following existing assets are worth preserving conceptually, even if implementation details change:
- FastAPI application server
- mission-scoped data model
- SQLite for current development stage
- local deployment strategy
- report type inventory
- template seeding concept
- per-mission indexing concept
- report-specific retrieval direction
- pending review before final document mutation
- DOCX export priority

The migration should not discard working ideas unnecessarily.
It should replace the parts that block the desired product shape.

---

## 3. Current baseline to phase out

The following current approaches should be treated as transitional or replaceable:
- Quill as the core editor foundation
- raw HTML as the long-term source of truth for authored documents
- full-document structured HTML edit generation as the main update path
- open stream lifecycle as the primary truth for long-running jobs
- section-awareness existing only as a design stub

---

## 4. Migration philosophy

### Rule 1
Do not try to build perfect Word parity before the architecture is correct.

### Rule 2
Do not try to make exhaustive evidence-driven updates feel like inline typing assistance.

### Rule 3
Stabilize the current system enough that it stops breaking while the new editor and suggestion model are introduced.

### Rule 4
Prefer introducing durable concepts first:
- job state
- suggestion entities
- revision state
- section identity

### Rule 5
Preserve export quality throughout the migration.

---

## 5. Phase overview

### Phase 0
Immediate stabilization of the current codebase

### Phase 1
Introduce the new domain model and job model without fully replacing the UI

### Phase 2
Replace the editor foundation with Tiptap/ProseMirror and establish the new document model

### Phase 3
Build inline assist on top of the new suggestion model

### Phase 4
Build coverage-mode grounded updates with duplicate prevention

### Phase 5
Build review, comments, and approval flow polish

### Phase 6
Optional collaboration and advanced workspace/admin features

---

## 6. Phase 0: immediate stabilization

## Goal
Make the current product less fragile while preparing the codebase for migration.

## Why this phase matters
The current system already works enough to demonstrate value, but update behavior is the biggest source of pain.
Before replacing the editor, the system should become easier to reason about and easier to debug.

## Phase 0 tasks

### 6.1 Add durable job records for update requests

Even if the old UI still streams output, each update action should create a job record.
This decouples user experience from stream completion semantics.

### 6.2 Add structured per-step timing logs

Add timings for:
- retrieval
- prompt assembly
- generation
- parse/validation
- pending edit persistence
- preview/application

### 6.3 Add durable failure records

Persist:
- job failure reason
- parse failure information
- fallback path usage
- invalid target count

### 6.4 Improve progress semantics

Move from generic "still waiting" behavior to structured progress states.

### 6.5 Review manifest/update behavior carefully

Ensure that incremental ingest and update behavior refreshes the source-of-truth state correctly after successful runs.
If new-or-changed detection remains stale, the system will keep reprocessing the same evidence.

### 6.6 Separate full-report update actions from scoped update actions in naming

Even before the full redesign, do not keep one ambiguous "update" concept in the code and UI.
Start distinguishing:
- generate first draft
- update from new evidence
- rewrite selected text
- refresh section

## Phase 0 deliverables
- durable job state for current update requests
- much better logs and failure visibility
- clearer command naming
- reduced ambiguity in current update path

---

## 7. Phase 1: introduce the target domain model

## Goal
Create the persistent concepts needed by the future system while disturbing the current product as little as possible.

## Phase 1 tasks

### 7.1 Add report revision support

Create a revision model and start checkpointing accepted or saved states.

### 7.2 Evolve pending edits into first-class suggestions

The existing `pending_edits` concept is a good seed, but it should grow into a suggestion model with:
- explicit suggestion type
- source job id
- revision id
- evidence refs
- status transitions

### 7.3 Add explicit section definitions

Introduce section definitions for each report template.
Do this before trying to implement real section-aware updating.

### 7.4 Add suggestion job model

Create a durable entity representing AI requests.

### 7.5 Begin mission settings support for ingest mode

Support MEL-controlled ingest behavior:
- auto-ingest
- manual ingest confirmation

## Phase 1 deliverables
- report revisions exist
- suggestions exist as durable objects
- explicit section schema exists
- job model exists
- mission settings begin to reflect future behavior

---

## 8. Phase 2: replace the editor foundation

## Goal
Move from Quill to a Tiptap/ProseMirror-based editor and establish a document-native editing substrate.

## Why this phase comes before advanced AI features
The future AI behavior depends on stable anchoring, structured document state, and stronger formatting support.
Those are much easier once the editor foundation is correct.

## Phase 2 tasks

### 8.1 Build a new editor shell

Create a new report editing experience backed by structured document state.

### 8.2 Recreate core formatting

At minimum support:
- bold
- italic
- underline
- headings
- lists
- indentation
- font options if feasible early
- image insertion or paste support
- tables if feasible

### 8.3 Create page-style presentation

Focus on:
- page framing
- margins
- polished document feel
- consistent typography

### 8.4 Map rigid templates into explicit document structures

Each report should instantiate from a template-backed structured document model.

### 8.5 Preserve export path

Either adapt the current DOCX exporter or create a clean conversion path from the new document model.

## Phase 2 deliverables
- Quill no longer defines the long-term editing path
- document model is structured and stable
- page-oriented editing exists
- formatting looks meaningfully more professional

---

## 9. Phase 3: build inline assist

## Goal
Deliver the first experience that genuinely feels like the intended Cursor + Docs hybrid.

## Phase 3 tasks

### 9.1 Selection-based AI actions

Support:
- rewrite
- shorten
- expand
- formalize
- operationalize
- convert list/paragraph

### 9.2 Cursor-based AI actions

Support:
- suggest next sentence
- insert paragraph here
- fill placeholder

### 9.3 Return suggestions, not direct edits

All AI output should be staged as suggestions.

### 9.4 Add accept/reject flows inside the new editor

The user should be able to review inline suggestions naturally.

### 9.5 Add minimal evidence support for scoped grounded actions

Some inline actions may still need evidence.
This should use speed-mode retrieval, not heavy report-refresh logic.

## Phase 3 deliverables
- first truly collaborative AI editing experience
- suggestions feel precise
- operator control is preserved
- latency is much better for authoring assistance

---

## 10. Phase 4: build grounded update jobs

## Goal
Replace the fragile full-document update experience with a suggestion-job driven grounded update system.

## Phase 4 tasks

### 10.1 Build evidence snapshot logic

Track what source state existed when a report was last updated or approved.

### 10.2 Build new-evidence detection summaries

When new files are ingested, the UI should show that new evidence is available rather than silently mutating the report.

### 10.3 Implement coverage-mode update jobs

Create jobs that:
- determine relevant new or changed evidence
- retrieve coverage-oriented evidence
- generate reviewable suggestions
- attach evidence refs

### 10.4 Implement duplicate prevention

Use both:
- provenance tracking
- semantic similarity checks

### 10.5 Introduce section-aware update targeting

Now that the section schema exists, implement real section-aware update planning.
This is the point where `sections.py`-style ideas become real product behavior instead of design notes.

## Phase 4 deliverables
- new evidence is visible to users
- updates are deliberate and reviewable
- duplicate proposal rate is reduced
- section targeting becomes real

---

## 11. Phase 5: review and approval polish

## Goal
Make the operator -> crew lead -> MEL workflow explicit and credible in-product.

## Phase 5 tasks

### 11.1 Add report status transitions

Implement:
- Draft
- In Review
- Crew Lead Approved
- MEL Approved / Final

### 11.2 Add comments

Allow users to leave review comments without editing text directly.

### 11.3 Add section or document review mode

Support reviewer workflows that do not require scanning the raw full history of edits manually.

### 11.4 Add final export actions and approval logging

Make finalization explicit and auditable.

## Phase 5 deliverables
- review flow matches the intended role model
- document workflow becomes operationally credible

---

## 12. Phase 6: later improvements

These are later-scope directions, not blockers for the core product:
- richer live collaboration presence
- more advanced comments UX
- deeper admin/debug console
- advanced ingest dashboards
- packaging/archive workflows
- more advanced auxiliary knowledge management

---

## 13. Recommended implementation order inside the codebase

This section is written for a coding agent or engineer.

## 13.1 First preserve and isolate

Before large changes:
- preserve current report export behavior
- preserve current mission and report persistence behavior
- isolate old editor code from new editor code
- isolate old update endpoints from new suggestion job endpoints

## 13.2 Then introduce new core entities

Implement in order:
1. revisions
2. suggestion jobs
3. suggestions
4. section schema
5. mission settings for ingest behavior

## 13.3 Then add new editor and new APIs

Do not wait until all backend redesign is complete before starting the new editor shell.
The UI and backend should evolve in parallel after the new entities exist.

## 13.4 Then retire the old pathways gradually

Deprecate rather than instantly delete:
- old update endpoint semantics
- editor-specific assumptions tied to Quill
- HTML-only mutation assumptions

---

## 14. Acceptance criteria by phase

## Phase 0 acceptance
- update requests create durable job records
- failures are diagnosable
- timing data exists for the major pipeline steps

## Phase 1 acceptance
- revisions, suggestions, and jobs exist as database-backed concepts
- report templates have explicit section identity

## Phase 2 acceptance
- a Tiptap/ProseMirror editor is usable for report editing
- page-style document layout exists
- core formatting is available

## Phase 3 acceptance
- selection-based AI actions work
- suggestions are reviewable and reversible
- inline AI feels meaningfully faster than the old update path

## Phase 4 acceptance
- new evidence can be surfaced without auto-editing the report
- update jobs create reviewable grounded suggestions
- duplicate prevention exists and visibly reduces repeated content
- section-aware targeting exists in real product behavior

## Phase 5 acceptance
- report status transitions are enforced
- comments and review actions exist
- crew lead and MEL approvals are represented in product behavior

---

## 15. Explicit guidance for Cursor or any coding agent

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

## 16. What to avoid

Avoid these traps:
- rebuilding everything at once
- overfitting more engineering into the old editor foundation
- treating chat as a separate product that bypasses suggestion review
- hiding long-running state inside one streaming endpoint
- implementing section updates before explicit section identity exists
- treating top-k retrieval as sufficient for completeness-sensitive document generation

---

## 17. Final migration thesis

The migration should produce a system where:
- the editor is document-native
- AI suggestions are first-class, durable, and reviewable
- updates are job-driven and evidence-aware
- retrieval supports both speed and coverage
- new evidence is visible and actionable
- duplicate reintroduction is actively controlled
- the operator, crew lead, and MEL workflow is real in the product

That is the standard the codebase should move toward.
