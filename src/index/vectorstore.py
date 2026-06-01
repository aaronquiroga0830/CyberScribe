"""
Vector store abstraction: FAISS (MVP) or Chroma.
Swap VECTOR_STORE_TYPE in .env to change backend without code changes in agents.
"""
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_core.embeddings import Embeddings

from config.settings import (
    INDEX_DIR,
    VECTOR_STORE_TYPE,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    OLLAMA_BASE_URL,
)
from src.ingest.chunking import chunk_documents


def get_embeddings() -> Embeddings:
    """Return embeddings model (local)."""
    if EMBEDDING_PROVIDER == "ollama":
        from langchain_community.embeddings import OllamaEmbeddings
        return OllamaEmbeddings(
            base_url=OLLAMA_BASE_URL,
            model=EMBEDDING_MODEL or "nomic-embed-text",
        )
    # Default: sentence-transformers
    from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
    )


def get_vectorstore(
    mission_id: str,
    documents: List[Document] | None = None,
    chunks: List[Document] | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> VectorStore:
    """
    Get or create a vector store for a mission.
    - If chunks are provided: use them as-is (no chunking).
    - If documents are provided: chunk, embed, and create/store index.
    - If neither: load existing index from disk (FAISS) or connect (Chroma).
    """
    index_path = INDEX_DIR / mission_id
    index_path.mkdir(parents=True, exist_ok=True)
    embeddings = get_embeddings()

    if VECTOR_STORE_TYPE == "chroma":
        return _chroma_store(index_path, documents, chunks, embeddings, chunk_size, chunk_overlap)
    return _faiss_store(index_path, documents, chunks, embeddings, chunk_size, chunk_overlap)


def _faiss_store(
    index_path: Path,
    documents: List[Document] | None,
    chunks: List[Document] | None,
    embeddings: Embeddings,
    chunk_size: int,
    chunk_overlap: int,
) -> VectorStore:
    from langchain_community.vectorstores import FAISS

    faiss_path = index_path / "faiss"
    if chunks:
        store = FAISS.from_documents(chunks, embeddings)
        store.save_local(str(faiss_path))
        return store
    if documents:
        chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        store = FAISS.from_documents(chunks, embeddings)
        store.save_local(str(faiss_path))
        return store
    # Load existing
    store = FAISS.load_local(
        str(faiss_path),
        embeddings,
        allow_dangerous_deserialization=True,
    )
    return store


def _chroma_store(
    index_path: Path,
    documents: List[Document] | None,
    chunks: List[Document] | None,
    embeddings: Embeddings,
    chunk_size: int,
    chunk_overlap: int,
) -> VectorStore:
    import chromadb
    from langchain_community.vectorstores import Chroma

    persist_dir = str(index_path / "chroma")
    collection_name = "mission_docs"

    if chunks:
        return Chroma.from_documents(
            chunks,
            embeddings,
            collection_name=collection_name,
            persist_directory=persist_dir,
        )
    if documents:
        chunks = chunk_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return Chroma.from_documents(
            chunks,
            embeddings,
            collection_name=collection_name,
            persist_directory=persist_dir,
        )
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )
