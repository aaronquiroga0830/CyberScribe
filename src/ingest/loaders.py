"""Load mission documents from disk. Normalize format for downstream chunking."""
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    DirectoryLoader,
    TextLoader,
    UnstructuredWordDocumentLoader,
    PyPDFLoader,
)
from langchain_community.document_loaders.base import BaseLoader


def infer_doc_type(file_path: Path, mission_path: Path) -> str:
    """
    Infer document type from path/filename for retrieval (timeline needs all crew logs, RMP needs broader set).
    Returns: "crew_log" | "findings" | "other"
    """
    path = Path(file_path)
    mission_path = Path(mission_path)
    try:
        rel = path.relative_to(mission_path)
    except ValueError:
        rel = path
    s = (str(rel) + path.name).lower().replace(" ", "_")
    if "crew_log" in s or "crewlog" in s:
        return "crew_log"
    if "finding" in s:
        return "findings"
    return "other"

# Map extensions to loaders. Add more as needed (e.g. UnstructuredExcelLoader).
LOADER_MAP = {
    ".txt": TextLoader,
    ".pdf": PyPDFLoader,
    ".docx": UnstructuredWordDocumentLoader,
}


def _get_loader_cls(path: Path) -> type[BaseLoader]:
    suffix = path.suffix.lower()
    return LOADER_MAP.get(suffix, TextLoader)


def load_file(path: Path, encoding: str = "utf-8") -> List[Document]:
    """Load a single file into LangChain Documents. Adds source metadata."""
    path = Path(path)
    if not path.is_file():
        return []
    loader_cls = _get_loader_cls(path)
    try:
        loader = loader_cls(str(path), encoding=encoding)
    except TypeError:
        loader = loader_cls(str(path))
    docs = loader.load()
    for d in docs:
        d.metadata.setdefault("source", str(path))
        d.metadata.setdefault("mission_file", path.name)
    return docs


def load_mission_documents(mission_path: str | Path) -> List[Document]:
    """
    Load all supported documents under a mission directory.
    mission_path: path to folder containing mission-specific files (e.g. crew logs, findings).
    Sets metadata doc_type ("crew_log" | "findings" | "other") for retrieval by report type.
    """
    mission_path = Path(mission_path)
    if not mission_path.is_dir():
        return []

    all_docs: List[Document] = []
    for ext in LOADER_MAP:
        for path in mission_path.rglob(f"*{ext}"):
            if path.is_file():
                docs = load_file(path)
                doc_type = infer_doc_type(path, mission_path)
                for d in docs:
                    d.metadata["doc_type"] = doc_type
                all_docs.extend(docs)

    # Fallback: any .txt via DirectoryLoader if you prefer glob-based
    if not all_docs:
        loader = DirectoryLoader(
            str(mission_path),
            glob="**/*.txt",
            loader_cls=TextLoader,
            show_progress=True,
        )
        all_docs = loader.load()
        for d in all_docs:
            src = d.metadata.get("source", "")
            d.metadata["doc_type"] = infer_doc_type(Path(src), mission_path)

    return all_docs
