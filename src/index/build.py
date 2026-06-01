"""Build (or rebuild) vector index for a mission from a source directory."""
import json
from pathlib import Path

from langchain_core.documents import Document

from config.settings import INDEX_DIR, MISSIONS_DIR, VECTOR_STORE_TYPE
from src.ingest.loaders import load_mission_documents
from src.ingest.chunking import chunk_documents
from src.ingest.manifest import write_manifest
from src.index.vectorstore import get_vectorstore


def mission_index_exists(mission_id: str) -> bool:
    """Return True if a valid index already exists (by_type + vector store), so we can skip rebuild on Update."""
    index_path = INDEX_DIR / mission_id
    by_type = index_path / "by_type"
    if not by_type.is_dir():
        return False
    if not any(by_type.glob("*.json")):
        return False
    if VECTOR_STORE_TYPE == "chroma":
        return (index_path / "chroma").is_dir()
    return (index_path / "faiss" / "index.faiss").exists() or (index_path / "faiss" / "index.pkl").exists()


def _save_chunks_by_type(mission_id: str, chunks: list[Document]) -> None:
    """Persist chunks grouped by doc_type so timeline can use all crew_log, RMP all docs."""
    index_path = INDEX_DIR / mission_id
    by_type_path = index_path / "by_type"
    by_type_path.mkdir(parents=True, exist_ok=True)
    by_type: dict[str, list[dict]] = {}
    for c in chunks:
        doc_type = (c.metadata.get("doc_type") or "other").strip() or "other"
        by_type.setdefault(doc_type, []).append({
            "page_content": c.page_content,
            "metadata": dict(c.metadata),
        })
    for doc_type, items in by_type.items():
        path = by_type_path / f"{doc_type}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=0)


def build_mission_index(
    mission_id: str,
    source_path: Path | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    cpt: str | None = None,
) -> None:
    """
    Load all documents from mission dir, chunk, embed, and persist vector index.
    Tags chunks with mission_id and cpt for mission isolation and retrieval/templates.
    """
    source_path = source_path or (MISSIONS_DIR / mission_id)
    if not source_path.is_dir():
        raise FileNotFoundError(f"Mission source path not found: {source_path}")

    documents = load_mission_documents(source_path)
    if not documents:
        raise ValueError(f"No supported documents found under {source_path}")

    # Build manifest of files in this ingest (path, doc_type, mtime) for incremental updates
    seen: set[str] = set()
    file_list: list[dict] = []
    for d in documents:
        src = d.metadata.get("source")
        if not src or src in seen:
            continue
        seen.add(src)
        try:
            mtime = Path(src).stat().st_mtime
        except OSError:
            mtime = 0.0
        file_list.append({"path": str(Path(src).resolve()), "doc_type": d.metadata.get("doc_type", "other"), "mtime": mtime})
    write_manifest(mission_id, source_path, file_list)

    chunks = chunk_documents(
        documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    for c in chunks:
        c.metadata["mission_id"] = mission_id
        if cpt:
            c.metadata["cpt"] = cpt
    _save_chunks_by_type(mission_id, chunks)
    get_vectorstore(
        mission_id=mission_id,
        chunks=chunks,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
