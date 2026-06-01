# Editor, UX, and Suggestion System Design

## 1. Why the editor is a first-order architectural decision

The current platform can generate and review content, but the next product depends on a much stronger editing substrate.
The target experience is not merely a textarea with AI features.
It is a document-centric workspace where operators feel like they are working inside a real mission report.

That means the editor choice affects:
- formatting fidelity
- suggestion anchoring
- duplicate-aware updates
- review behavior
- future collaboration
- versioning strategy
- export quality

The editor is not an implementation detail.
It is a foundational product decision.

---

## 2. Recommended editor direction

## 2.1 Primary recommendation

Use Tiptap / ProseMirror as the foundation for the next editor layer.

Reasons:
- stronger structured document model than Quill
- better support for rich editing and custom node behavior
- stronger long-term foundation for suggestion anchoring and review UX
- better foundation for future collaboration than the current HTML-centric model
- flexible enough to build a mission-specific document experience instead of adapting to a generic editor's limits

## 2.2 What the editor must support in v1

The editor must support:
- bold
- italic
- underline
- font family
- font size
- headings
- bullets
- numbered lists
- indentation
- links
- tables if feasible in the initial pass
- image insertion or pasted screenshots
- copy and paste from common office tools as well as reasonably possible
- page-oriented layout presentation
- explicit section anchors
- suggestion overlays or tracked-change-like presentation

## 2.3 Honest scope line on Word parity

The browser editor should aim for near-Word pagination fidelity, but it should not promise literal parity with Word's rendering engine in the first implementation.
The design target is:
- page-like layout
- margins and document frame
- section-aware editing
- high quality export
- a document-native feeling throughout drafting

The first implementation should prioritize perceived document realism and functional reviewability over impossible perfect parity.

---

## 3. Document model

## 3.1 Source of truth

The long-term source of truth should be a structured document model, not freeform HTML strings.

Recommended source of truth:
- ProseMirror JSON for editor content

Derived representations:
- rendered HTML for display layers or preview layers where needed
- normalized export representation for DOCX/PDF generation
- diff-ready spans or ranges for suggestion application

## 3.2 Why not raw HTML as the main document model

Raw HTML as the core editable state makes the following harder:
- precise suggestion anchoring
- sentence/span level review
- rich structured transformations
- clean section targeting
- collaborative editing later
- semantic analysis of document coverage

HTML can still exist as an output or interchange layer.
It should not remain the long-term primary authoring model.

## 3.3 Template structure in the editor

Every template should be instantiated into a document tree with explicit section nodes or section metadata.
This allows:
- reliable section targeting
- report-specific UI affordances
- section-aware updates
- easier document validation
- future section-specific retrieval and generation strategies

---

## 4. Page-oriented editing UX

## 4.1 Layout goal

The document should feel like a real report page, not a floating rich text card.

Desired qualities:
- visible page width and height boundaries
- document margins
- consistent line spacing and typography
- scroll through pages rather than a single borderless text field
- section headers that visually map to document structure

## 4.2 Toolbar direction

The toolbar should feel closer to a simplified Word/Docs toolbar than a developer markdown toolbar.

Recommended initial groups:
- text formatting
- paragraph and heading controls
- list controls
- insert controls
- AI actions
- review controls
- export controls

## 4.3 Focus behavior

The editor screen should support a document-first focus mode.
The document should remain the main pane.
AI, evidence, and comments should support the document, not dominate it.

---

## 5. Main screen layout

A three-zone layout is the best default direction.

## 5.1 Left panel

Mission navigation:
- Overview
- RMP
- Timeline
- AAR
- SITREP
- Source Documents
- Mission Settings if user has permission

## 5.2 Center pane

Document editor:
- page-oriented editing canvas
- report content
- visible tracked suggestions
- reviewable ranges
- section identity

## 5.3 Right panel

Context panel with tabs:
- Suggestions
- Evidence
- Comments
- Chat
- Job/Activity state

This layout supports the desired Cursor + Docs hybrid model without turning the product into a dashboard-first UI.

---

## 6. AI interaction design

AI should be passive and on demand.
It should not constantly inject itself into the user's work.

## 6.1 Selection-based actions

When text is selected, the user should be able to invoke actions like:
- Rewrite
- Shorten
- Expand
- Formalize
- Make more operational
- Convert to bullets
- Convert to paragraph
- Cite evidence
- Update from mission evidence

These actions should create suggestions, not immediate document mutations.

## 6.2 Cursor-based actions

When no text is selected, the user should be able to invoke actions like:
- Suggest next sentence
- Insert paragraph here
- Draft this section from mission evidence
- Fill placeholder

Again, the result should be staged as a suggestion unless the user explicitly chooses an insertion behavior that is still reversible and reviewable.

## 6.3 Report-level actions

At the report level, the user should be able to trigger:
- Generate first draft
- Update from new evidence
- Review all pending suggestions
- Compare with prior approved state

---

## 7. Suggestion model

## 7.1 Suggestion principles

Suggestions must be:
- reviewable
- reversible
- anchored to specific content locations
- grounded when evidence matters
- independent from the live draft until accepted

## 7.2 Smallest unit of work

The smallest AI work unit should be a sentence or a short span.
This gives the platform the ability to feel precise and collaborative rather than all-or-nothing.

## 7.3 Smallest useful unit of approval

Users should be able to accept or reject at the following levels:
- sentence or small span
- grouped consecutive change set
- section
- all pending suggestions

## 7.4 Suggested status model for suggestions

Each suggestion should support states like:
- pending
- accepted
- rejected
- superseded
- invalidated because base text changed

## 7.5 Suggested suggestion types

Suggestion types should at least include:
- replace_span
- insert_after_span
- insert_before_span
- delete_span
- replace_section
- insert_section_content
- comment_only
- evidence_note

---

## 8. Tracked-changes-style UX

The user asked for tracked changes behavior, and that should be treated as a core product property.

## 8.1 Rendering direction

The editor should visually distinguish:
- proposed insertions
- proposed deletions
- accepted document content
- pending suggestion regions

The exact rendering style can vary, but the user should be able to tell at a glance what is proposed versus applied.

## 8.2 Review interactions

For each suggestion, the user should be able to:
- inspect the proposed change
- inspect rationale if available
- inspect evidence references if grounded
- accept
- reject
- navigate to the next suggestion

## 8.3 Section review mode

There should be a section-level review path where users can review all pending edits affecting a section without scanning the full document manually.

---

## 9. Evidence UX

Grounded AI behavior is not enough by itself.
The platform needs a good evidence experience so users can trust and verify suggestions.

## 9.1 Evidence visibility

The right-side panel should be able to show:
- which evidence supported a selected suggestion
- short evidence snippets
- source document identity
- optionally confidence or rationale notes

## 9.2 What evidence should not do

Final report output should not carry source citations if that is not desired for mission products.
Evidence is for authoring and review, not necessarily for final artifact presentation.

## 9.3 Evidence interaction goals

Users should be able to answer these questions quickly:
- why is this suggestion being proposed
- which document supports it
- whether the source is new or already seen
- whether the evidence conflicts with other evidence

---

## 10. Chat design

Chat is in scope, but it should not become a separate product inside the product.
It should be another front door into the same suggestion and retrieval system.

## 10.1 Chat must be able to

Chat in v1 should be able to:
- answer mission questions
- answer report questions
- summarize relevant evidence
- explain the basis for suggestions
- stage edits
- create suggestions directly in the document

## 10.2 Chat should not bypass review

Even if chat creates a suggestion directly in the report, it should still follow the same suggestion/review rules as any other AI-generated proposal.

## 10.3 Chat scope levels

Chat should support these scopes:
- report-wide
- section-specific
- mission-wide

The active scope should be explicit in the UI so the user understands what corpus and document context the response is using.

## 10.4 Chat action examples

Examples of valid chat actions:
- "Summarize all new findings relevant to the RMP"
- "Propose wording for this section based on the newly added crew logs"
- "Insert a concise executive summary suggestion for this report"
- "What changed in the evidence since the last approved Timeline update"
- "Explain why this suggestion was created"

---

## 11. Concurrency and collaboration direction

Real-time collaboration is desired, but the most advanced collaboration polish is later scope.
Still, the editor foundation chosen now should not block it.

## 11.1 V1 collaboration stance

V1 should at least support:
- multiple authorized users on the same mission
- concurrent editing direction in architecture
- comments
- clear attribution in revisions or suggestion history where feasible

## 11.2 Later collaboration improvements

Later collaboration can add:
- live cursors
- live selections
- richer presence indicators
- stronger conflict handling
- collaborative commenting polish

The important thing now is to choose a document model and architecture that can grow into that direction.

---

## 12. Comments and review collaboration

Comments are part of the desired product and should support the review chain.

Users should be able to:
- leave comments on document locations or sections
- review comments without directly changing text
- use comments during crew lead and MEL review stages

This helps separate discussion from direct draft mutation.

---

## 13. User-experience safeguards

The editor must not feel locked or frozen when AI work is happening.

## 13.1 Non-blocking rule

Long-running AI work must not block normal editing.
If an evidence-driven update is in progress, the user should still be able to work in the document.

## 13.2 Job-awareness rule

The UI should clearly indicate when:
- new evidence is available
- an update job is running
- suggestions are ready for review
- a suggestion became invalid because the user changed the underlying text

## 13.3 Auto-behavior rule

The system should not automatically apply edits after ingest.
Instead it should mark that new evidence is available and let the user decide when to request updates.

---

## 14. Practical v1 UX goals

A good first implementation should feel like this:
- the user opens a mission report and sees a real document canvas
- the toolbar feels familiar
- the user highlights text and requests an AI rewrite
- the suggestion appears quickly and clearly
- grounded updates appear as reviewable changes, not as invisible overwrites
- the user can inspect evidence on the right side
- review never feels like guessing what changed

That is much more important than chasing every Word feature immediately.

---

## 15. Editor and UX success definition

The editor and UX work is successful when:
- users stop feeling like they are working in a fragile prototype
- AI suggestions feel collaborative rather than intrusive
- report updates are understandable and reviewable
- the document remains the center of attention
- the platform feels credible as an operator workspace rather than only a generation demo
