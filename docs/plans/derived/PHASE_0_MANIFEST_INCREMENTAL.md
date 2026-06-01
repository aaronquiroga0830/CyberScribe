# Phase 0 — Manifest vs `last_used_doc_paths` (audit)

**Scope:** `indexes/<mission_id>/manifest.json` and per-report `reports.last_used_doc_paths` after successful runs.

## Roles

| Artifact | Written by | Purpose |
|----------|------------|---------|
| `manifest.json` | `build_mission_index` → `write_manifest` | Snapshot of **ingested** files (absolute path, `doc_type`, `mtime`) at last **full** index build. |
| `last_used_doc_paths` | `_run_structured_edits` after retrieval | JSON list of doc paths the **last structured update** considered (union of prior baseline + paths used in that run). |

## Incremental structured updates

1. If `last_used_doc_paths` is **NULL** (reset, first run, or never set), retrieval uses the **full** mission retriever / all chunks for that report type.
2. If set, `get_new_docs_context_for_report` calls `new_or_changed_files(mission_id, source_path)`:
   - Scans the mission directory and compares to **manifest** entries (path + mtime).
   - Returns text only for files that are **new** or **mtime-changed** and match the report’s doc types.
3. If there are **no** new/changed files for that report, the code **falls back** to full retriever context (see `server.py` `_run_structured_edits`).
4. After a successful structured path, `set_report_docs_used` stores the path set used for that run.

## Stale or surprising cases (by design / limits)

- **HTTP pipeline skips index rebuild** when `mission_index_exists` is true. The manifest is **not** refreshed on those runs. `new_or_changed_files` still compares **live disk mtimes** to the **last manifest**; new files and edits to existing files are detected. Files **removed** from disk are not explicitly pruned from `last_used_doc_paths` (harmless for retrieval; paths simply may no longer exist).
- **Scheduler** (`run_mission_cycle`) always runs `build_mission_index`, so manifest stays aligned with daily full ingest for missions touched by the scheduler.
- **Path normalization:** Manifest and scans use `Path.resolve()`-style absolute paths in `manifest.py`; retriever metadata `source` should stay consistent with those paths for stable unions in `last_used_doc_paths`.
- **Full refresh override:** Clients may send `update_intent: "full_refresh"` (or `"generate_first_draft"`) so structured updates **ignore** the stored baseline and pull full corpus context for that job.

## Conclusion

No code defect was found that would silently skip all updates; the main operational note is that **manifest lags** until the next index rebuild, while **mtime-based** diffing still drives incremental context. Use **Full source refresh** in the UI (or `full_refresh` on the API) when operators want to force a full-context structured run without clearing `last_used_doc_paths` in the DB.
