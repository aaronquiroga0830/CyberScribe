"""Mission-scoped retriever: loads mission index and returns a LangChain retriever."""
import json
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from config.settings import INDEX_DIR
from src.index.vectorstore import get_vectorstore
from src.ingest.loaders import load_file
from src.ingest.chunking import chunk_documents
from src.ingest.manifest import new_or_changed_files
from src.auxiliary_service import load_auxiliary_documents

# Report type -> doc types used for retrieval (timeline: crew_log only; others: all)
REPORT_DOC_TYPES = {
    "timeline": ["crew_log"],
    "rmp": ["crew_log", "findings", "other"],
    "aar": ["crew_log", "findings", "other"],
    "sitrep": ["crew_log", "findings", "other"],
}


class FixedListRetriever(BaseRetriever):
    """Retriever that always returns the same list of documents (ignores query). Used for timeline (all crew_log) and RMP (all docs)."""
    docs: list[Document]

    def _get_relevant_documents(self, query: str) -> list[Document]:
        return self.docs


class _AuxAugmentedRetriever(BaseRetriever):
    """Prepend auxiliary mission docs to semantic search results."""

    inner: BaseRetriever
    aux_docs: list[Document]

    def _get_relevant_documents(self, query: str) -> list[Document]:
        got = list(self.inner.invoke(query))
        return list(self.aux_docs) + got


def _load_chunks_by_type(mission_id: str, doc_types: list[str]) -> list[Document]:
    """Load persisted chunks for given doc_types (e.g. ['crew_log'] or ['crew_log', 'findings', 'other'])."""
    by_type_path = INDEX_DIR / mission_id / "by_type"
    if not by_type_path.is_dir():
        return []
    out: list[Document] = []
    for doc_type in doc_types:
        path = by_type_path / f"{doc_type}.json"
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            out.append(Document(page_content=item["page_content"], metadata=item.get("metadata", {})))
    return out


def get_mission_retriever(
    mission_id: str,
    k: int = 8,
    documents: list | None = None,
    report_type: str | None = None,
) -> BaseRetriever:
    """
    Get a retriever for the given mission.
    - report_type "timeline": returns all crew_log chunks (no query; timeline needs full crew logs).
    - report_type "rmp": returns all chunks (crew_log + findings + other) for broader RMP context.
    - report_type None: semantic search with k (legacy).
    If documents is provided, builds index from those docs. Otherwise loads existing index / by_type.
    """
    aux_docs = load_auxiliary_documents(mission_id, report_type)

    if report_type and report_type in REPORT_DOC_TYPES:
        doc_types = REPORT_DOC_TYPES[report_type]
        docs = _load_chunks_by_type(mission_id, doc_types)
        if docs:
            merged = (aux_docs + docs) if aux_docs else docs
            return FixedListRetriever(docs=merged)

    # Semantic search (or fallback when by_type not yet built)
    store: VectorStore = get_vectorstore(mission_id=mission_id, documents=documents)
    inner = store.as_retriever(search_kwargs={"k": k})
    if aux_docs:
        return _AuxAugmentedRetriever(inner=inner, aux_docs=aux_docs)
    return inner


def get_new_docs_context_for_report(
    mission_id: str,
    report_type: str,
    source_path: Path,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> Optional[tuple[str, list[str]]]:
    """
    Build context from only new-or-changed documents relevant to this report type.
    Returns (concatenated chunk text, list of doc paths used) or None if no new/changed docs.
    """
    doc_types = REPORT_DOC_TYPES.get(report_type, [])
    if not doc_types:
        return None
    new_changed = new_or_changed_files(mission_id, source_path)
    filtered = [x for x in new_changed if x.get("doc_type") in doc_types]
    if not filtered:
        return None
    source_path = Path(source_path)
    documents: list[Document] = []
    paths_used: list[str] = []
    for item in filtered:
        path = Path(item["path"])
        if not path.is_file():
            continue
        paths_used.append(str(path.resolve()))
        docs = load_file(path)
        dt = item.get("doc_type", "other")
        for d in docs:
            d.metadata["doc_type"] = dt
            d.metadata.setdefault("source", str(path))
        documents.extend(docs)
    if not documents:
        return None
    chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    context_str = "\n\n".join(c.page_content for c in chunks if c.page_content)
    return (context_str, paths_used)
