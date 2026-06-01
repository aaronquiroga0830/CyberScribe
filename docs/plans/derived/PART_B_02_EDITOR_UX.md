# PART B — Editor, UX, suggestion system (`02`)

**Source:** [../planning_pack/02_EDITOR_UX_AND_SUGGESTION_SYSTEM.md](../planning_pack/02_EDITOR_UX_AND_SUGGESTION_SYSTEM.md)

---

## §1 Why editor is first-order

- **Current:** Quill in [web/app.ts](../../web/app.ts).
- **Delta:** Phase 2 — PM/Tiptap foundation before advanced AI (`04` §15.2).

---

## §2 Recommended editor direction

### §2.1 Primary: Tiptap / ProseMirror

- **Delta:** Phase 2 spike + migration path from Quill.

### §2.2 v1 capabilities (formatting, tables, images, paste)

- **Current:** Quill subset.
- **Delta:** Match list in pack §2.2.

### §2.3 Word parity honesty

- **Delta:** Page-like layout without promising Word engine parity.

---

## §3 Document model

### §3.1 SoT: ProseMirror JSON

- **Current:** HTML strings in SQLite.
- **Delta:** Phase 2 store JSON; HTML as cache/export.

### §3.2 Why not raw HTML SoT

- **Verify:** Anchors, collaboration, section targeting (`01` Problem 3).

### §3.3 Template structure in editor

- **Delta:** Phase 1–2 section nodes/metadata.

---

## §4 Page-oriented editing UX (4.1–4.3)

- **Delta:** Phase 2 — margins, frame, toolbar groups, focus mode.

---

## §5 Main screen layout (5.1–5.3)

- **Current:** Sidebar + main + stream/pending areas — **partial** three-zone idea.
- **Delta:** Right panel tabs: Suggestions, Evidence, Comments, Chat, Jobs (`02` §5.3); wire Jobs to `pipeline-jobs` API Phase 0 UI.

---

## §6 AI interaction (6.1–6.3)

- **Current:** Report-level Update / Run pipeline.
- **Delta:** Phase 3 selection/cursor/report actions → suggestions only.

---

## §7 Suggestion model (7.1–7.5)

- **Current:** `pending_edits` list + preview — **partial**.
- **Delta:** Span-level types (`replace_span`, …), statuses (superseded, invalidated), revision binding Phase 1.

---

## §8 Tracked-changes UX (8.1–8.3)

- **Current:** Preview highlights — **partial**.
- **Delta:** Phase 2–3 true tracked visuals + section review mode.

---

## §9 Evidence UX (9.1–9.3)

- **Current:** Sources with pending — **partial**.
- **Delta:** Right panel evidence for selected suggestion Phase 3–4.

---

## §10 Chat design (10.1–10.4)

- **Current:** None.
- **Delta:** Phase 3–4; same suggestion pipeline (`04` §16 avoid bypass).

---

## §11 Concurrency (11.1–11.2)

- **Delta:** Phase 6+ presence; Phase 1–2 architecture must not block CRDT/Yjs later.

---

## §12 Comments and review collaboration

- **Delta:** Phase 5 — `03` §3.10.

---

## §13 UX safeguards

### §13.1 Non-blocking

- **Verify:** Long jobs must not freeze editor — use job polling + background workers.

### §13.2 Job-awareness

- **Delta:** Phase 0 UI — show job state from `GET .../pipeline-jobs`.

### §13.3 No auto-apply after ingest

- **Verify:** Surface “new evidence” instead (`02` + Phase 4).

---

## §14 Practical v1 UX goals

- **Verify:** After Phase 3 — user test against pack §14 bullets.

---

## §15 Editor success definition

- **Verify:** Pack §15 as milestone checklist.
