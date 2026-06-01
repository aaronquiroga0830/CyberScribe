"""
Section-aware incremental updates for mission reports (Phase 4 §10.5).

Maps new/changed source files (by doc_type) to (report_type, section_key) pairs that are
most likely to need refreshed content. Used for job telemetry and UI hints — the pipeline
still runs full structured edits per report; this list guides future scoped generation.
"""
from __future__ import annotations

# doc_type from infer_doc_type → (report_type, section_key) aligned with SECTION_DEFINITION_SEED
DOC_TYPE_TO_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "findings": [
        ("rmp", "findings"),
        ("rmp", "recommendations"),
        ("aar", "objectives"),
        ("aar", "outcomes"),
        ("sitrep", "risks"),
    ],
    "crew_log": [
        ("timeline", "chronological_events"),
        ("rmp", "body_intro"),
        ("rmp", "executive_summary"),
        ("aar", "mission_summary"),
        ("aar", "actions_taken"),
        ("sitrep", "current_status"),
        ("sitrep", "key_events"),
    ],
    "other": [
        ("rmp", "body_intro"),
        ("rmp", "executive_summary"),
        ("sitrep", "current_status"),
        ("sitrep", "key_events"),
    ],
}


def sections_to_update(mission_id: str, new_or_changed_items: list[dict]) -> list[tuple[str, str]]:
    """
    Given new/changed file records `{path, doc_type, mtime}`, return deduplicated
    (report_type, section_key) pairs likely affected.

    `mission_id` is reserved for future per-mission overrides (e.g. custom templates).
    """
    _ = mission_id
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in new_or_changed_items:
        if not isinstance(item, dict):
            continue
        dt = (item.get("doc_type") or "other").strip().lower()
        pairs = DOC_TYPE_TO_SECTIONS.get(dt) or DOC_TYPE_TO_SECTIONS["other"]
        for rt, sk in pairs:
            key = (rt, sk)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
