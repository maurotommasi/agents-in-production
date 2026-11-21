"""Request and response schemas for the HTTP API (Pydantic models)."""
from pydantic import BaseModel, Field


class DocumentIn(BaseModel):
    """One document to index. The id is chosen by the caller so that
    re-ingesting the same document updates it instead of duplicating."""

    id: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=500)
    text: str = Field(min_length=1)
    # Free form metadata, for example {"source": "help-centre",
    # "language": "en", "product": "payments"}. Search can filter on it.
    metadata: dict = Field(default_factory=dict)


class BulkIn(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1, max_length=1000)


class IngestResult(BaseModel):
    document_id: str
    chunks_indexed: int


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    # Exact match filters on document metadata, for example
    # {"language": "en"}. Applied before ranking.
    filters: dict = Field(default_factory=dict)


class SearchHit(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    text: str
    score: float
    metadata: dict


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit]
    took_ms: float
