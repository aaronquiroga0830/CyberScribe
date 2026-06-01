# Platform value proposition (proposal tone)

> **Superseded as the read-first doc:** Use [PROJECT_MASTER.md](PROJECT_MASTER.md) for the full picture (motivation, product, technical, roadmap). This file remains for focused reference.

Use this section in capability briefs, proposals, and stakeholder summaries. For technical architecture and file roles, see [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## Lead statement

**By combining mission-scoped, evidence-grounded RAG with section-level AI suggestions and a formal human-in-the-loop review workflow, our platform helps operators turn distributed mission artifacts into unified, approvable mission reports—without applying AI changes until they are explicitly accepted and approved.**

Operators work in structured mission reports; AI proposes changes with evidence references; crew leads and MEL review status, comments, and approval before documents are finalized and exported.

## How it works

1. **Access:** Users log into the mission workspace and open mission-scoped reports (RMP, Timeline, AAR, SITREP).
2. **Ingest:** Operator and mission source files are ingested into a **per-mission** vector index (isolated from other missions).
3. **Draft with AI:** As operators write, the system offers **section- and block-level** suggestions grounded in retrieved mission evidence; inline assist supports on-demand help in the editor.
4. **Collaborate on one draft:** Contributions from mission artifacts and multiple editors feed **shared report drafts** within the same mission workspace.
5. **Protect with humans in the loop:** AI never silently overwrites the document—users **accept or reject** each proposal; reports move through **draft → review → crew lead → MEL → final** with an approval log before export.

## Alternate phrasing (optional)

**Shorter lead:**

> Using mission-isolated RAG and section-aware AI assistance inside a collaborative document workspace, the platform accelerates report drafting while ensuring every AI suggestion and final export remains under human review and approval.

**Cause → effect rhythm:**

> By using mission-scoped RAG to ingest operator artifacts and propose grounded edits section by section, our platform consolidates mission evidence into shared report drafts that operators edit, reviewers approve, and leadership finalizes—preserving human-in-the-loop control at every step.

## Canonical product sentence

Mission-scoped, human-in-the-loop RAG workspace for collaborative document creation—Word/Docs-style editing, grounded AI suggestions, evidence-aware incremental updates, and formal mission review workflows. (See [planning pack README](plans/planning_pack/00_README.md).)

## Wording guide

| Prefer | Avoid (unless qualified) |
|--------|--------------------------|
| human-in-the-loop, accept/reject, approvable | autonomous report generation |
| mission-scoped / mission-isolated | enterprise knowledge base (cross-mission) |
| evidence-grounded suggestions | AI writes the report for you |
| formal review workflow (crew lead, MEL) | real-time multi-user editing (not fully implemented) |
| consolidates mission artifacts into reports | aggregates all operators automatically |
