"""Vector stores.

A store keeps chunks and their vectors and answers nearest neighbour
queries: given a query vector, return the chunks whose vectors are
closest by cosine similarity.

Two backends ship here:
- InMemoryStore: numpy based, exact search. Perfect for local runs
  and small collections (up to a few hundred thousand chunks).
- PgVectorStore: PostgreSQL with the pgvector extension. This is the
  production backend: durable, indexed (HNSW), filterable, and it
  lives in the same database most teams already operate.
"""
import json
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    title: str
    text: str
    metadata: dict = field(default_factory=dict)


def _matches(metadata: dict, filters: dict) -> bool:
    return all(metadata.get(k) == v for k, v in filters.items())


class InMemoryStore:
    def __init__(self):
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        for chunk, vec in zip(chunks, vectors):
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = np.asarray(vec, dtype=np.float32)

    def delete_document(self, document_id: str) -> int:
        doomed = [cid for cid, c in self._chunks.items() if c.document_id == document_id]
        for cid in doomed:
            del self._chunks[cid]
            del self._vectors[cid]
        return len(doomed)

    def search(self, query_vector: list[float], top_k: int, filters: dict) -> list[tuple[Chunk, float]]:
        if not self._chunks:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        scored: list[tuple[Chunk, float]] = []
        for cid, chunk in self._chunks.items():
            if filters and not _matches(chunk.metadata, filters):
                continue
            # Vectors are L2 normalised, so the dot product is the
            # cosine similarity.
            score = float(np.dot(q, self._vectors[cid]))
            scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._chunks)


class PgVectorStore:
    """Production store on PostgreSQL + pgvector. See schema.sql."""

    def __init__(self, database_url: str):
        import psycopg  # imported lazily so local runs need no driver

        self._conn = psycopg.connect(database_url, autocommit=True)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        with self._conn.cursor() as cur:
            for chunk, vec in zip(chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (chunk_id, document_id, title, text, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        title = EXCLUDED.title, text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding
                    """,
                    (chunk.chunk_id, chunk.document_id, chunk.title, chunk.text,
                     json.dumps(chunk.metadata), vec),
                )

    def delete_document(self, document_id: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            return cur.rowcount

    def search(self, query_vector: list[float], top_k: int, filters: dict) -> list[tuple[Chunk, float]]:
        # The <=> operator is pgvector cosine distance. The HNSW index
        # keeps this fast at millions of chunks. Metadata filters use
        # the JSONB containment operator.
        sql = """
            SELECT chunk_id, document_id, title, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM chunks
            WHERE (%s = '{}'::jsonb OR metadata @> %s::jsonb)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        filt = json.dumps(filters)
        with self._conn.cursor() as cur:
            cur.execute(sql, (query_vector, filt, filt, query_vector, top_k))
            rows = cur.fetchall()
        return [
            (Chunk(r[0], r[1], r[2], r[3], r[4] or {}), float(r[5])) for r in rows
        ]

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            return int(cur.fetchone()[0])


def build_store(settings):
    if settings.store_backend == "pgvector":
        return PgVectorStore(settings.database_url)
    return InMemoryStore()
