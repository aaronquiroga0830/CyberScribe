"""
Ingest manifest: track which files were in the mission at last index build.
Used to compute new-or-changed files for incremental report updates.
"""
import json
from pathlib import Path
from typing import List, Dict, Any

from config.settings import INDEX_DIR
from src.ingest.loaders import LOADER_MAP, infer_doc_type


def _manifest_path(mission_id: str) -> Path:
    return INDEX_DIR / mission_id / "manifest.json"


def read_manifest(mission_id: str) -> List[Dict[str, Any]]:
    """Read the manifest for this mission. Returns list of {path, doc_type, mtime}. Empty if missing."""
    path = _manifest_path(mission_id)
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return list(data) if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_manifest(mission_id: str, source_path: Path, file_list: List[Dict[str, Any]]) -> None:
    """Write the manifest. file_list = [{path, doc_type, mtime}, ...]. path should be absolute or relative to source_path."""
    path = _manifest_path(mission_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(file_list, f, ensure_ascii=False, indent=0)


def scan_source_files(source_path: Path) -> List[Dict[str, Any]]:
    """Public: list supported files under source_path as {path, doc_type, mtime}."""
    return _scan_source_files(source_path)


def _scan_source_files(source_path: Path) -> List[Dict[str, Any]]:
    """Scan source_path for supported extensions, return list of {path, doc_type, mtime}."""
    source_path = Path(source_path)
    if not source_path.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for ext in LOADER_MAP:
        for p in source_path.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0.0
            doc_type = infer_doc_type(p, source_path)
            out.append({"path": str(p.resolve()), "doc_type": doc_type, "mtime": mtime})
    return out


def new_or_changed_files(mission_id: str, source_path: Path) -> List[Dict[str, Any]]:
    """
    Compare current source dir to manifest. Return list of {path, doc_type, mtime} for files
    that are new or have changed (mtime different). Paths are absolute.
    """
    current = _scan_source_files(source_path)
    manifest = read_manifest(mission_id)
    by_path = {item["path"]: item for item in manifest}
    result: List[Dict[str, Any]] = []
    for item in current:
        path = item["path"]
        if path not in by_path:
            result.append(item)
            continue
        if by_path[path].get("mtime") != item.get("mtime"):
            result.append(item)
    return result
