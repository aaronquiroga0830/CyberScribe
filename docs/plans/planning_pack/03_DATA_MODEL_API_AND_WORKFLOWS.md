# Data Model, APIs, and Workflow Design

## 1. Purpose of this document

This document defines the backend-facing design for the target platform.
It is intentionally implementation-oriented.
It describes the data model, service boundaries, jobs, workflows, retrieval logic, duplicate prevention, and API surface needed to evolve the current MVP into the intended system.

---

## 2. High-level system model

The system should be organized around the following core entities:
- MissionWorkspace
- MissionMember
- SourceDocument
- ReportTemplate
- Report
- ReportSection
- ReportRevision
- SuggestionJob
- Suggestion
- Comment
- ApprovalAction
- AuxiliaryKnowledgeSource

The main design change from the current system is that suggestion objects and revisions become first-class entities, rather than being treated as side effects of a single update call.

---

## 3. Proposed data model

## 3.1 MissionWorkspace

Represents a mission-scoped environment.

Suggested fields:
- id
- name
- status
- classification
- source_path
- output_path
- ingest_mode
- created_at
- updated_at
- created_by_user_id
- mel_user_id
- settings_json
- mission_metadata_json

Possible `ingest_mode` values:
- auto
- manual

Possible status values:
- active
- paused
- review
- complete
- archived

## 3.2 MissionMember

Maps users to roles and permissions inside a mission.

Suggested fields:
- mission_id
- user_id
- role
- permissions_json
- created_at
- updated_at

Roles:
- operator
- crew_lead
- mel
- viewer

## 3.3 SourceDocument

Represents an ingested or ingestable mission source file.

Suggested fields:
- id
- mission_id
- path
- display_name
- checksum
- mtime
- doc_type
- classification
- source_system
- unit
- document_date
- ingest_status
- was_auto_ingested
- is_authoritative
- metadata_json
- created_at
- updated_at

Suggested `ingest_status` values:
- discovered
- queued
- ingested
- failed
- removed

## 3.4 ReportTemplate

Represents the rigid structure for a report type.

Suggested fields:
- id
- report_type
- version
- name
- template_schema_json
- created_at
- updated_at
- created_by_user_id

The template schema should define explicit section identity.

## 3.5 Report

Represents the current working report instance inside a mission.

Suggested fields:
- id
- mission_id
- report_type
- template_id
- status
- current_document_json
- current_html_cache
- current_export_cache_path
- created_at
- updated_at
- created_by_user_id
- current_revision_id
- last_approved_revision_id
- last_generated_from_job_id
- last_known_evidence_snapshot_id

Possible statuses:
- draft
- in_review
- crew_lead_approved
- final

## 3.6 ReportSection

Represents explicit section identity inside a report.
This may be stored as template-level structure and projected into report content, or persisted per report when needed.

Suggested fields:
- id
- report_id
- section_key
- display_title
- order_index
- required
- section_policy_json

## 3.7 ReportRevision

Represents a saved document state after accepted changes or explicit save checkpoints.

Suggested fields:
- id
- report_id
- revision_number
- author_type
- author_user_id
- source_job_id
- source_suggestion_ids_json
- document_json
- summary_text
- created_at

Possible `author_type` values:
- human
- ai
- system

## 3.8 SuggestionJob

Represents an AI action request that can produce one or more suggestions.

Suggested fields:
- id
- mission_id
- report_id
- job_type
- scope_type
- scope_payload_json
- retrieval_mode
- status
- created_by_user_id
- created_at
- started_at
- finished_at
- error_message
- progress_json
- evidence_snapshot_id

Possible `job_type` values:
- inline_rewrite
- inline_insert
- first_draft
- update_from_new_evidence
- section_refresh
- chat_request
- contradiction_check
- executive_summary_generation

Possible `scope_type` values:
- selection
- cursor
- section
- whole_report
- chat_context

Possible `retrieval_mode` values:
- none
- speed
- coverage
- auxiliary_only
- mixed

Possible `status` values:
- queued
- running
- completed
- failed
- cancelled

## 3.9 Suggestion

Represents a specific proposed edit.
This is one of the most important entities in the new design.

Suggested fields:
- id
- job_id
- mission_id
- report_id
- section_key
- suggestion_type
- anchor_json
- old_content_json
- proposed_content_json
- rationale_text
- evidence_refs_json
- duplicate_fingerprint
- similarity_guard_json
- status
- created_against_revision_id
- created_at
- reviewed_by_user_id
- reviewed_at

Possible `suggestion_type` values:
- replace_span
- insert_after
- insert_before
- delete_span
- replace_section
- note_only

Possible `status` values:
- pending
- accepted
- rejected
- superseded
- invalidated

`anchor_json` should describe where the change is targeted.
It must be strong enough to revalidate against a modified document.

## 3.10 Comment

Suggested fields:
- id
- mission_id
- report_id
- section_key
- anchor_json
- author_user_id
- body
- status
- created_at
- updated_at

Possible statuses:
- open
- resolved

## 3.11 ApprovalAction

Suggested fields:
- id
- mission_id
- report_id
- from_status
- to_status
- action_type
- actor_user_id
- note
- created_at

Possible `action_type` values:
- submit_for_review
- approve_as_crew_lead
- return_for_changes
- approve_as_mel
- reopen

## 3.12 AuxiliaryKnowledgeSource

Represents optional curated official knowledge usable for certain report behaviors.

Suggested fields:
- id
- name
- scope
- enabled
- source_path
- metadata_json
- created_at
- updated_at

The important point is that this corpus is curated and local, not an unrestricted internet feed.

---

## 4. Suggested service boundaries

## 4.1 Workspace service

Responsibilities:
- create mission workspaces
- update mission settings
- manage users and permissions
- expose mission metadata and statuses

## 4.2 Document service

Responsibilities:
- create and manage report instances
- return current document state
- persist direct user edits
- manage revisions
- manage section identity

## 4.3 Suggestion service

Responsibilities:
- create suggestion jobs
- persist suggestions
- validate suggestion anchors
- apply accepted suggestions
- reject or invalidate suggestions

## 4.4 Retrieval service

Responsibilities:
- execute speed-mode retrieval
- execute coverage-mode retrieval
- optionally retrieve from auxiliary knowledge
- return evidence refs suitable for review UI

## 4.5 Ingest service

Responsibilities:
- discover files
- ingest files
- update indexes
- maintain manifests and checksums
- expose new evidence state for each mission/report

## 4.6 Approval service

Responsibilities:
- manage report state transitions
- enforce role-based approval gates
- log approval actions

## 4.7 Export service

Responsibilities:
- export current approved report to DOCX
- later export to PDF
- ensure template fidelity and metadata compliance

---

## 5. Retrieval design in more detail

## 5.1 Mode split

The retrieval layer must explicitly support:
- speed mode
- coverage mode
- optional auxiliary retrieval

## 5.2 Speed mode

Inputs:
- current document context
- current selection or cursor location
- active section
- optionally a very small set of evidence snippets

Outputs:
- minimal prompt-ready context
- enough data for fast, scoped AI help

Speed mode should avoid broad corpus scans when unnecessary.

## 5.3 Coverage mode

Inputs:
- report type
- target sections or whole report
- relevant mission documents
- last evidence snapshot
- dedupe state

Outputs:
- broad evidence set
- grouped evidence candidates
- evidence refs that can be attached to suggestions

Coverage mode should optimize for completeness, not just top-k relevance.

## 5.4 Auxiliary knowledge retrieval

Auxiliary knowledge should be optionally layered into retrieval when:
- the report type permits it
- the action type permits it
- the mission settings permit it
- the user or workflow explicitly requests it

This is especially relevant for RMP-like tasks involving official cyber reference material.

---

## 6. Duplicate-prevention design

The product requires that updates from newly ingested documents do not simply restate content already in the draft.
This requires explicit duplicate prevention logic.

## 6.1 Duplicate-prevention inputs

The duplicate-prevention system should compare new candidate content against:
- the current document text
- accepted suggestions already applied
- evidence already represented in the report if tracked
- existing pending suggestions

## 6.2 Duplicate-prevention methods

Use both:
- provenance/evidence-based checks
- semantic similarity checks

### Provenance examples
- this evidence chunk has already been linked to accepted content in this section
- this source file has already materially influenced the report through a prior suggestion
- the same evidence fingerprint already exists in a suggestion history record

### Similarity examples
- candidate sentence is semantically near-duplicate of existing sentence
- new paragraph restates an existing finding with only wording changes

## 6.3 Suggested implementation strategy

Maintain:
- evidence fingerprinting
- suggestion-level provenance refs
- section-level evidence coverage summaries
- similarity search over accepted text and accepted suggestions

This does not need to be perfect in v1, but the architecture must make it possible.

---

## 7. Job model and progress model

## 7.1 Why jobs are required

Long-running AI behavior should not be represented solely by an open streaming response.
The system needs durable state for:
- progress
- failure inspection
- retry behavior
- suggestion persistence
- UI state recovery

## 7.2 Job creation flow

1. user invokes action
2. backend creates `SuggestionJob`
3. job is queued or started
4. retrieval occurs if needed
5. suggestions are generated
6. suggestions are saved
7. job status becomes completed or failed
8. UI loads suggestions independently of the stream lifecycle

## 7.3 Progress model

Progress should be expressed in structured terms such as:
- retrieval_started
- retrieval_completed
- generation_started
- suggestions_generated
- suggestions_saved
- completed

This is more useful than a generic spinner.

---

## 8. API surface proposal

The exact path names can vary, but the system should support an API family roughly like this.

## 8.1 Workspace APIs

- `POST /api/workspaces`
- `GET /api/workspaces`
- `GET /api/workspaces/{mission_id}`
- `PATCH /api/workspaces/{mission_id}`
- `POST /api/workspaces/{mission_id}/members`
- `PATCH /api/workspaces/{mission_id}/members/{user_id}`
- `PATCH /api/workspaces/{mission_id}/settings`

## 8.2 Source document APIs

- `GET /api/workspaces/{mission_id}/documents`
- `POST /api/workspaces/{mission_id}/documents/discover`
- `POST /api/workspaces/{mission_id}/documents/ingest`
- `DELETE /api/workspaces/{mission_id}/documents/{document_id}`
- `POST /api/workspaces/{mission_id}/documents/{document_id}/reclassify`

## 8.3 Report APIs

- `GET /api/workspaces/{mission_id}/reports`
- `GET /api/workspaces/{mission_id}/reports/{report_type}`
- `PATCH /api/workspaces/{mission_id}/reports/{report_type}`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/initialize`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/export/docx`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/export/pdf`

## 8.4 Suggestion APIs

- `POST /api/workspaces/{mission_id}/reports/{report_type}/jobs`
- `GET /api/workspaces/{mission_id}/reports/{report_type}/jobs/{job_id}`
- `GET /api/workspaces/{mission_id}/reports/{report_type}/suggestions`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/suggestions/{suggestion_id}/accept`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/suggestions/{suggestion_id}/reject`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/suggestions/accept-all`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/suggestions/reject-all`

## 8.5 Review and approval APIs

- `POST /api/workspaces/{mission_id}/reports/{report_type}/submit-for-review`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/approve-crew-lead`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/approve-mel`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/return-for-changes`

## 8.6 Chat APIs

- `POST /api/workspaces/{mission_id}/reports/{report_type}/chat`
- `POST /api/workspaces/{mission_id}/reports/{report_type}/chat/{message_id}/create-suggestion`

## 8.7 Activity APIs

- `GET /api/workspaces/{mission_id}/activity`
- `GET /api/workspaces/{mission_id}/jobs`
- `GET /api/workspaces/{mission_id}/new-evidence-summary`

---

## 9. Workflow definitions

## 9.1 Mission initialization workflow

1. MEL creates workspace
2. MEL sets mission metadata and ingest mode
3. MEL adds members and permissions
4. system instantiates all report templates immediately
5. source documents are discovered and optionally ingested
6. reports begin in Draft status

## 9.2 User editing workflow

1. user opens a report
2. user edits document directly
3. user saves document or autosave occurs
4. system creates a human-authored revision checkpoint as appropriate

## 9.3 Inline AI suggestion workflow

1. user selects text or places cursor
2. user invokes an AI action
3. backend creates job with `retrieval_mode = speed` or `none`
4. model generates one or more suggestions
5. suggestions are rendered in the editor and side panel
6. user accepts or rejects
7. accepted suggestions create a new revision

## 9.4 Full-draft generation workflow

1. user explicitly requests first draft generation
2. backend creates a job with `retrieval_mode = coverage`
3. retrieval gathers relevant evidence for the report template
4. system generates suggestion sets or a structured first-draft proposal
5. user reviews and accepts/rejects
6. accepted changes become the working draft

## 9.5 New-evidence update workflow

1. documents are discovered and ingested
2. workspace shows new evidence is available
3. user requests update
4. backend determines relevant new or changed evidence
5. retrieval gathers evidence in coverage mode
6. duplicate-prevention logic compares candidate content against current state
7. system generates suggestions only for net-new or revised content
8. user reviews and applies accepted suggestions

## 9.6 Chat-assisted workflow

1. user asks a question in report or mission scope
2. backend answers using the appropriate retrieval mode
3. user can request that the answer be staged as edits or suggestions
4. system creates suggestions under a chat-originated job
5. user reviews and accepts/rejects

## 9.7 Approval workflow

1. operator finishes drafting and marks report ready for review
2. crew lead reviews and either approves or returns for changes
3. MEL reviews and final-approves
4. final report can be exported and packaged

---

## 10. Versioning and invalidation rules

Suggestions must be created against a specific report revision.
If the user changes the document after a suggestion is created, the system must be able to decide whether that suggestion is:
- still valid
- partially valid
- invalidated

This is necessary for reliable collaborative editing.

Suggested rule:
- every suggestion stores the revision it was created against
- anchor resolution happens before accept/apply
- invalid anchors require suggestion invalidation or regeneration

---

## 11. Observability and tuning hooks

The future system needs better observability than the current prototype behavior.

At minimum, collect timing and error data for:
- file discovery
- ingest
- chunking
- retrieval
- dedupe
- prompt assembly
- model generation
- suggestion persistence
- suggestion application
- export

Admin/debug views can come later, but the underlying instrumentation should be added early.

---

## 12. Implementation note relative to the current codebase

The current system already has useful seeds for this design:
- report state persistence
- pending edits concept
- report-type retrieval distinctions
- manifest-based new/changed file detection
- last-used-doc tracking

The migration does not need to throw away those ideas.
It needs to turn them into more explicit first-class services and entities.
