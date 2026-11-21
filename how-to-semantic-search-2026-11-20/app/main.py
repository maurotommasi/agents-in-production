"""Semantic search service: FastAPI application.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --host 0.0.0.0 --port 8080

Then index documents and search:
    python client_demo.py

Production shape: the app is stateless. All state lives in the
store (PostgreSQL + pgvector), so you can run many replicas behind
a load balancer and scale ingestion and search independently.
"""
import time
import uuid

from fastapi import FastAPI, HTTPException

from .config import settings
from .embeddings import build_embedder
from .models import BulkIn, DocumentIn, IngestResult, SearchHit, SearchIn, SearchOut
from .store import Chunk, build_store
from .text import chunk_text

app = FastAPI(title="Semantic Search Service", version="1.0.0")
embedder = build_embedder(settings)
store = build_store(settings)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "embedder": embedder.model_name,
            "store": settings.store_backend, "chunks": store.count()}


def _index_document(doc: DocumentIn) -> IngestResult:
    if len(doc.text) > settings.max_document_chars:
        raise HTTPException(413, f"document too large: {len(doc.text)} chars")
    # Re-indexing replaces the old chunks of this document.
    store.delete_document(doc.id)
    pieces = chunk_text(doc.text, settings.chunk_chars, settings.chunk_overlap)
    chunks = [
        Chunk(
            chunk_id=f"{doc.id}#{i}",
            document_id=doc.id,
            title=doc.title,
            text=piece,
            metadata=dict(doc.metadata),
        )
        for i, piece in enumerate(pieces)
    ]
    vectors = embedder.embed([c.text for c in chunks])
    store.upsert(chunks, vectors)
    return IngestResult(document_id=doc.id, chunks_indexed=len(chunks))


@app.post("/documents", response_model=IngestResult)
def add_document(doc: DocumentIn) -> IngestResult:
    return _index_document(doc)


@app.post("/documents/bulk", response_model=list[IngestResult])
def add_documents(payload: BulkIn) -> list[IngestResult]:
    return [_index_document(doc) for doc in payload.documents]


@app.delete("/documents/{document_id}")
def remove_document(document_id: str) -> dict:
    removed = store.delete_document(document_id)
    return {"document_id": document_id, "chunks_removed": removed}


@app.post("/search", response_model=SearchOut)
def search(payload: SearchIn) -> SearchOut:
    started = time.perf_counter()
    query_vector = embedder.embed([payload.query])[0]
    results = store.search(query_vector, payload.top_k, payload.filters)
    hits = [
        SearchHit(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            text=chunk.text,
            score=round(score, 4),
            metadata=chunk.metadata,
        )
        for chunk, score in results
    ]
    took_ms = (time.perf_counter() - started) * 1000.0
    return SearchOut(query=payload.query, hits=hits, took_ms=round(took_ms, 2))


@app.get("/stats")
def stats() -> dict:
    return {"chunks": store.count(), "embedder": embedder.model_name,
            "request_id": uuid.uuid4().hex[:8]}
