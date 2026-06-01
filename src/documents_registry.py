"""List mission source documents vs manifest (ingest dashboard)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ingest.manifest import read_manifest, scan_source_files


def list_mission_documents(mission_id: str, source_path: Path) -> dict[str, Any]:
    source_path = Path(source_path)
    if not source_path.is_dir():
        return {"files": [], "manifest": [], "error": "source_path is not a directory"}
    scanned = scan_source_files(source_path)
    manifest = read_manifest(mission_id)
    man_by = {m.get("path"): m for m in manifest if isinstance(m, dict)}
    enriched = []
    for item in scanned:
        p = item.get("path", "")
        mrow = man_by.get(p, {})
        enriched.append(
            {
                "path": p,
                "doc_type": item.get("doc_type"),
                "mtime": item.get("mtime"),
                "in_manifest": p in man_by,
                "manifest_mtime": mrow.get("mtime"),
            }
        )
    return {"files": enriched, "manifest_count": len(manifest)}
