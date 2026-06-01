# Solution Workflow – Visual Diagram Spec (Revised)

> **Superseded as the read-first doc:** Use [PROJECT_MASTER.md](PROJECT_MASTER.md) for the full picture (motivation, product, technical, roadmap). This file remains for focused reference.

**Goal:** A clear, attractive flowchart of the mission RAG report system. Use whatever shapes and layout look best (nodes, rounded cards, icons, etc.). Prioritize clarity and a polished look.

**Flow (left to right):**

---

## 1. Input

- **Label:** "Input" or "Source documents"
- **Caption / subtext:** "Per mission. Supported: text (.txt), PDF, Word (.docx)."
- **Note:** Excel/CSV are not currently supported; omit or list only the three above. "Per mission" = one source folder per mission.
- **Arrow:** Single arrow out → Normalization.

---

## 2. Normalization

- **Label:** "Normalization"
- **Caption / subtext:** "Chunking · Metadata tagging (doc_type: crew_log, findings, other) · Embedding"
- **Note:** doc_type is used so Timeline can use only crew_log, RMP/AAR/SITREP use all types.
- **Arrows:** In ← Input. Out → Vector store.

---

## 3. Vector store

- **Label:** "Vector store (FAISS)" or "Vector store"
- **Caption / subtext:** "Per-mission index. Chunks grouped by doc_type for retrieval. Manifest for incremental (new/changed docs)."

- **Arrows:** In ← Normalization. Out → RAG system.

---

## 4. Templates

- **Label:** "Templates"
- **Caption / subtext:** "Report types: AAR, RMP, SITREP, Mission Timeline. Document skeletons + template-as-query for retrieval and prompts."
- **Note:** Feeds into RAG: which report type, which retrieval query, and which edit/generation prompt.
- **Arrow:** Single arrow into RAG system (e.g. from above or side).

---

## 5. RAG system

- **Label:** "RAG system" or "RAG (LLM + Retriever)"
- **Caption / subtext:** "Ollama phi3 + LangChain. Retriever by report type. Block-level edit proposals (JSON); fallback to full draft if none valid."
- **Note:** LLM returns structured edits (target_block_id, operation, new_html). 
- **Arrows:** In ← Vector store, In ← Templates. Out → Backend.

---

## 6. Backend

- **Label:** "Backend"
- **Caption / subtext:** "FastAPI. Orchestrates pipeline (index when needed, structured edits per report type). REST API + SSE streaming. SQLite: missions, reports, pending edits. Writes .docx to output path on Accept/Save."
- **Note:** Pipeline skips index build if `mission_index_exists`. Incremental update uses only new/changed docs when last_used is set; Reset clears that so next Update uses all docs.
- **Arrows:** In ← RAG system. Out → Front-end.

---

## 7. Front-end

- **Label:** "Front-end" or "Front-end platform"
- **Caption / subtext:** "UI; Report list and single-report view. Quill editor; proposed-changes panel (accept/reject per edit or all). Update / Reset from sidebar; preview with highlights."
- **Note:** Hash routing. Fetches report, pending-edits, preview HTML. Accept (single or all) triggers apply then refetch; no separate "Apply" button.
- **Arrows:** In ← Backend. Two-way ↔ Output location. Two-way ↔ End user.

---

## 8. Output location

- **Label:** "Output location"
- **Caption / subtext:** "Mission output path. Approved report content written as .docx on Accept or Save."
- **Arrows:** Two-way with Front-end only (backend writes; front-end/API can reference or list).

---

## 9. End user

- **Label:** "End user"
- **Caption / subtext:** "Review draft, accept/reject edits, edit content, trigger Update or Reset. Human-in-the-loop."
- **Note:** Can use a simple user/person icon or figure.
- **Arrows:** Two-way with Front-end only.

---

## Flow summary (for the AI)

```
Input → Normalization → Vector store → RAG system ← Templates
RAG system → Backend → Front-end ↔ Output location
Front-end ↔ End user
```

**Layout and style:** Left-to-right flow. Shapes can be rounded rectangles, circles, cards, or icons. Simple color scheme (e.g. data/storage vs compute vs user-facing). Optional callouts: "Human-in-the-loop" near Front-end ↔ End user; "Per-mission" near Input or Vector store.

---

