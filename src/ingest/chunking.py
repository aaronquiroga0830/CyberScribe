"""Chunk documents for vector store. Normalization happens here if needed."""
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def _normalize_text(doc: Document) -> Document:
    """Optional: normalize whitespace, encoding, etc. per doc."""
    if doc.page_content:
        doc.page_content = " ".join(doc.page_content.split())
    return doc


def chunk_documents(
    documents: List[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    normalize: bool = True,
) -> List[Document]:
    """
    Split documents into chunks for embedding and retrieval.
    Preserves metadata (source, mission_file) on each chunk.
    """
    if normalize:
        documents = [_normalize_text(d) for d in documents]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(documents)
