# Product and Architecture Master Plan

## 1. Executive summary

The next version of this platform should not be treated as a small patch on top of the current update flow.
It should be treated as a transition from a reviewable report-generation MVP into a mission-scoped collaborative document workspace.

The current product is already useful in one important way: it proves that mission-isolated RAG, template-seeded reports, local indexing, and human review can work together in a single environment.
However, the current interaction model is still dominated by long-running full-document updates, structured HTML edits, fragile streaming expectations, and a text-editor experience that does not match the intended end-state.

The target product is different:
- operators work directly in a document-first workspace
- the editor feels closer to Word or Google Docs than a plain rich text field
- AI is invoked on demand, not constantly
- AI proposes edits instead of silently mutating the draft
- suggestions are grounded in mission evidence when evidence matters
- suggestions are fast for inline help and thorough for evidence-driven updates
- new evidence is surfaced explicitly and can drive incremental updates
- duplicate reintroduction is prevented using both provenance and similarity checks
- the workspace supports an operator -> crew lead -> MEL workflow

The key product and engineering shift is this:

**The system must separate fast inline assist from heavier grounded update jobs.**

Trying to force both behaviors through one full-document structured edit pipeline is the main reason the current experience feels slow, brittle, and unlike Cursor or Docs.

---

## 2. Product definition

### 2.1 Canonical product statement

This platform is a mission-scoped, human-in-the-loop RAG workspace for collaborative document creation.
It ingests mission documents and rigid document templates, maintains mission-isolated retrieval and indexing, supports full-draft generation and incremental evidence-driven updates, allows operators to work in a Word/Docs-like editing experience, and requires human acceptance or rejection of AI suggestions before changes are applied.

### 2.2 What the product is

The product is:
- an AI-assisted report-writing workspace
- a collaborative mission document workspace
- a mission-scoped RAG system for grounded drafting and updating
- a formal review and approval environment for mission documents

### 2.3 What the product is not

The product is not:
- an autonomous report generator that silently rewrites content
- a general mission management platform unrelated to document workflow
- a cross-mission knowledge lake where mission content blends together
- a fully generic internet-grounded writing assistant
- a chat-only interface where the document is secondary

---

## 3. Core goals

### 3.1 User-facing goals

The platform must:
- substantially reduce the time required to create reports and plans
- reduce operator stress related to manual aggregation and document rewriting
- provide a polished document editing experience throughout drafting, not only at export time
- preserve trust by requiring grounded evidence when evidence matters
- let humans remain decisional owners of document changes

### 3.2 Technical goals

The platform must:
- isolate missions at the workspace, storage, and retrieval layers
- support both full-draft generation and incremental updates
- avoid duplicate content when new evidence is added after users have already updated the draft manually
- support multiple report types with rigid template structures
- handle both fast and exhaustive AI workloads through distinct execution paths
- preserve export quality, especially for DOCX

### 3.3 Non-negotiables

The following are locked requirements:
- mission isolation
- human-in-the-loop AI application
- operator accept/reject control
- crew lead review
- MEL final authority and mission configuration authority
- rigid templates with explicit section identity
- on-demand AI, not constant auto-writing
- source-grounded suggestions when evidence matters
- strong document editing UX
- duplicate-aware incremental updating
- near-Word page-aware editing as a target for the browser experience

---

## 4. Roles and permissions

## 4.1 Roles

### Operator / Analyst
Primary drafter.
Can edit reports, request AI assistance, review suggestions, and accept or reject AI changes.

### Crew Lead
Reviewer and correctness gate.
Can edit reports, review operator work, approve document correctness, and move the document toward final approval.

### MEL
Mission workspace owner, mission-level admin, and final approver.
The MEL is the same role as the mission lead in this product model.

The MEL can:
- initialize a mission workspace
- assign user access and permissions
- choose ingest behavior for the mission
- add or remove mission documents
- tune mission requirements and reporting emphasis
- influence mission-scoped drafting constraints
- approve final output

### Read-only user
Can view mission documents and report states without editing.
Useful for personnel who need mission visibility but are not actively drafting or approving.

## 4.2 Permission direction

At minimum, the system should support permissions for:
- workspace administration
- document editing
- AI suggestion acceptance/rejection
- review/approval actions
- read-only access
- mission configuration changes

The permission model should be mission-scoped, not global only.

---

## 5. Workspace model

## 5.1 Definition of a workspace

A workspace is a mission-scoped environment in which only mission-authorized users can access mission documents, mission drafts, suggestions, workflows, and approval states.

## 5.2 Contents of a workspace

A workspace contains:
- mission metadata
- mission settings
- user permissions
- source documents
- rigid templates
- report drafts
- report revisions
- AI suggestions
- approvals and comments
- retrieval/index state
- optional curated auxiliary knowledge approved for that mission or report class

## 5.3 Isolation model

Each mission must have isolated:
- source corpus
- indexes
- drafts
- report revisions
- suggestions
- approvals
- job state
- user permissions and mission settings

Cross-mission reuse is out of scope except for reusable templates and curated external knowledge that is explicitly permitted.

## 5.4 Mission lifecycle

The mission lifecycle should look like this:
1. MEL initializes workspace
2. templates are instantiated immediately
3. mission metadata and settings are configured
4. users are granted access
5. source documents are ingested
6. users edit drafts and request AI assistance
7. new evidence is surfaced over time
8. users request updates or draft generation as needed
9. crew lead reviews
10. MEL approves final output
11. workspace is packaged/archived later through a future workflow

---

## 6. Report model

## 6.1 Report types in scope

The system must support all of the following as first-class report types:
- RMP
- Timeline
- AAR
- SITREP

All matter to the product.
None should be treated as a throwaway report type.

## 6.2 Template behavior

Templates are rigid.
Each report starts from its template immediately when a mission is initialized.
AI does not automatically generate a first draft unless the user explicitly requests it.

## 6.3 Section model

Every report template must define explicit named sections from day one.
This is a hard requirement.
The system must not rely on inferring section structure from rendered HTML after the fact.

Each section definition should eventually include:
- report type
- section identifier
- display title
- order
- whether the section is required
- optionally, section-specific retrieval policy
- optionally, section-specific generation policy

## 6.4 Draft quality requirement

Documents should look polished throughout drafting, not only at export.
The browser experience should aim for near-Word page-aware editing.
DOCX export must remain high quality.

---

## 7. Current-state diagnosis of the uploaded codebase

This section is intentionally concrete and tied to the current codebase.

## 7.1 What currently exists

The current codebase already provides several solid foundations:
- FastAPI as the app and API surface
- a single-page browser UI
- SQLite mission/report persistence
- per-mission indexing and report state
- report types for `rmp`, `timeline`, `aar`, and `sitrep`
- current and pending report content storage
- pending edit storage
- report acceptance and rejection behavior
- mission-specific vector artifacts and `by_type/*.json` retrieval artifacts
- local-model integration and report-specific prompts

## 7.2 What the current architecture is good at

The current system is good at proving:
- mission isolation can be enforced
- templates can seed report state
- report generation can be wired into the mission lifecycle
- a local-only stack is feasible
- pending review before application is possible

## 7.3 What the current architecture is not yet good at

The current system is not yet a strong document workspace because:
- the editor is not the right long-term foundation
- streaming behavior is tied to long-running generation paths rather than a robust job model
- the default update behavior is still structurally close to full-document mutation
- section-aware updating has not actually been implemented
- the system is still optimized more for report generation than for collaborative drafting

## 7.4 Most important current-code findings

The current codebase shows the following architectural facts:
- `REPORT_TYPES` already includes `rmp`, `timeline`, `aar`, and `sitrep`
- `reports` stores `current_content`, `pending_content`, `pending_sources`, `current_updated_at`, and `last_used_doc_paths`
- `pending_edits` exists as a persistence concept
- retrieval already distinguishes report document types
- `timeline` is currently recall-biased toward crew logs by using all crew log chunks when `by_type` data exists
- `rmp`, `aar`, and `sitrep` currently use all mission document categories when `by_type` data exists
- `manifest.json` is already used for incremental new-or-changed file detection
- `sections.py` is still a design stub returning no section targets

## 7.5 Primary current-state problems

### Problem 1: one update mechanism is doing too much

The current system tries to use long-running structured edit generation as both:
- the document update mechanism
- the apparent interactive suggestion mechanism

That is the wrong abstraction for the target product.

### Problem 2: section-aware updating is not yet real

The product vision assumes targeted updating.
The code currently still falls back to full-document logic in too many cases.

### Problem 3: HTML/block mutation is not a strong long-term source of truth

Block-level HTML edits can be useful as an intermediate migration technique, but they are not the right long-term authoring model for a collaborative Word-like editor.

### Problem 4: the user experience is not document-native enough

A Word/Docs-like collaborative workflow needs:
- a stronger editor substrate
- a stronger suggestion model
- a better review interaction model
- a more reliable job/progress model

### Problem 5: update jobs and inline assistance need different service shapes

Inline assistance should be fast, local, and selection-oriented.
Grounded report updates should be asynchronous, evidence-aware, and review-oriented.

---

## 8. Future-state architecture

The target architecture should be made of the following layers.

## 8.1 Workspace layer

Responsibilities:
- mission initialization
- mission settings
- mission roles and permissions
- mission metadata
- ingest configuration
- report inventory
- report status lifecycle

## 8.2 Editor layer

Responsibilities:
- document editing
- page-oriented rendering
- formatting commands
- explicit section anchors
- tracked suggestion rendering
- comments and review behavior
- future concurrent editing foundation

Recommended direction:
- Tiptap / ProseMirror as the foundation
- document-native JSON state as the editing source of truth

## 8.3 Suggestion layer

Responsibilities:
- represent AI proposals without directly mutating the draft
- track suggestion provenance, scope, status, and rationale
- support sentence/span/section level review
- power both inline assist and chat-created edits

## 8.4 Retrieval layer

Responsibilities:
- mission-local retrieval
- coverage retrieval when completeness matters
- speed retrieval when latency matters
- optional auxiliary retrieval from curated local official sources
- evidence traceability

## 8.5 Update/job layer

Responsibilities:
- build async suggestion jobs
- manage job state, progress, and errors
- allow independent generation for different targets
- avoid tying document state to a single streaming response

## 8.6 Review layer

Responsibilities:
- operator suggestion acceptance or rejection
- crew lead review behavior
- MEL approval
- report status transitions

## 8.7 Export layer

Responsibilities:
- high-quality DOCX output
- PDF output later or second
- formatting fidelity preservation
- final packaging

---

## 9. Two-mode AI architecture

This is the single most important system decision.

The product must support two distinct AI workload classes.

## 9.1 Mode A: inline assist

Used for:
- rewrite selected text
- shorten or expand text
- formalize or operationalize language
- suggest a sentence or paragraph at cursor
- convert list to paragraph or paragraph to list
- answer a question and stage a targeted edit

Characteristics:
- low latency
- small scope
- current selection or local document context
- may use little or no retrieval
- should return complete suggestions rather than streaming raw tokens into the live document

## 9.2 Mode B: grounded update

Used for:
- update report or section from newly ingested evidence
- generate first draft from mission evidence
- create grounded executive summary
- update timeline from new actions
- perform completeness-oriented refreshes

Characteristics:
- may be slower
- evidence-heavy
- may require broad recall and deduplication
- should run as a job
- should return reviewable suggestion objects

## 9.3 Why the split is necessary

Without this split, the system is forced to choose between:
- fast but incomplete behavior
- complete but sluggish behavior

The product needs both.
Therefore the architecture must support both explicitly.

---

## 10. Retrieval strategy

The system cannot rely on a single top-k semantic retrieval strategy for all report types and actions.

## 10.1 Retrieval mode A: coverage mode

Coverage mode is used when missing relevant details is unacceptable.

Use coverage mode for:
- timeline updates
- findings aggregation
- evidence-driven report refreshes
- any report section where omission risk is operationally significant

Coverage mode behavior:
- metadata filters first
- report-type aware source narrowing
- broad recall or exhaustive inclusion where appropriate
- deduplication after retrieval
- optional chunk grouping by event/finding/phase
- evidence tracking for what has already been represented in the draft

## 10.2 Retrieval mode B: speed mode

Speed mode is used when the user is actively authoring and expects rapid results.

Use speed mode for:
- rewrite selected text
- local stylistic help
- cursor-based drafting suggestions
- small scoped insertions

Speed mode behavior:
- primarily local document context
- optionally a small number of retrieved evidence snippets
- reduced prompt size
- optimized for responsiveness

## 10.3 Report-specific retrieval direction

### Timeline
Must be completeness-biased.
The system should strongly prefer not missing actions.
Eventually, timeline updates should move toward event-level extraction and deduplication rather than simple whole-document synthesis.

### RMP
Should support both mission-evidence grounding and optional curated official guidance.
The auxiliary knowledge path matters more here than for some other report types.

### SITREP
Should be delta-aware, especially when updating from newly ingested evidence.

### AAR
Should support broad synthesis across phases, events, decisions, and lessons learned.

## 10.4 Auxiliary official knowledge

Optional side retrieval from sources like MITRE, CVEs, and local official reference material should be:
- admin-curated
- local to the deployment, not open-web by default
- selectively applied by report type or action
- auditable in provenance

---

## 11. Duplicate prevention requirement

This requirement is central and must not be treated as a small detail.

When new evidence is ingested and the user requests an update, the system must avoid proposing content that is already represented in the draft.
This includes content that may have been:
- written manually by the user
- accepted previously from AI suggestions
- already covered from prior evidence-driven updates

Duplicate prevention must use both:
- provenance/evidence tracking
- semantic similarity

This means the system should maintain enough structure to answer questions like:
- which evidence already contributed to this section or sentence
- whether new evidence is materially new or already represented
- whether a proposed edit is redundant with existing content

---

## 12. Review and approval model

## 12.1 Suggestion rule

AI never silently auto-applies edits.
AI proposes.
Humans review.
Humans accept or reject.

## 12.2 Role behavior

Operators:
- review suggestions
- accept or reject them
- edit directly

Crew leads:
- validate correctness and completeness
- review document state before final approval stage

MEL:
- approves final output
- can also influence workspace settings and requirements earlier in the mission lifecycle

## 12.3 Report status model

The report lifecycle should initially be:
- Draft
- In Review
- Crew Lead Approved
- MEL Approved / Final

---

## 13. Recommended long-term technical decisions

### Keep
- FastAPI
- mission-scoped storage model
- SQLite for now
- local deployment model
- template-first report model
- report-specific retrieval direction
- DOCX as a primary output format

### Replace or redesign
- Quill as the editor foundation
- HTML block mutation as the long-term source of truth
- one giant update request as the main unit of AI work
- single-stream completion semantics as the primary progress model

### Add
- Tiptap/ProseMirror editor foundation
- document-native suggestion objects
- suggestion job model
- explicit section model
- duplicate-aware update logic
- mission-setting controlled ingest behavior
- chat as an interface into the same grounded suggestion system

---

## 14. Product success definition

The product will be meaningfully closer to the target state when all of the following are true:
- users work in a polished document-native editor
- AI actions are on demand and predictable
- updates do not freeze or break the editor
- inline suggestions feel fast
- evidence-driven updates feel reliable and reviewable
- new evidence is surfaced clearly
- duplicate suggestions are substantially reduced
- users can accept or reject sentence/span suggestions cleanly
- crew lead and MEL workflows are explicit in the product
- DOCX export remains strong

---

## 15. Final architectural thesis

The future system should be built around this principle:

**The document is the primary workspace, suggestions are first-class review objects, retrieval is mission-isolated and mode-aware, and AI assistance is valuable only when it improves speed without sacrificing trust.**
