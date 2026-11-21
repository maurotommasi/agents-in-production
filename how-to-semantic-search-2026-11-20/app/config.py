"""Service configuration, read from environment variables.

Every setting has a local default so the service runs on a laptop with
zero setup. In production you override the values through the
environment of the container or the orchestrator, never in code.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Which embedder to use: "hashing" (offline, no API key) or "openai".
    embedder: str = os.getenv("EMBEDDER", "hashing")
    # Which store to use: "memory" (local) or "pgvector" (production).
    store_backend: str = os.getenv("STORE_BACKEND", "memory")
    # Postgres connection string, only used by the pgvector store.
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://search:search@localhost:5432/search"
    )
    # OpenAI API key, only used by the OpenAI embedder.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "text-embedding-3-small")
    # Vector size. Must match the embedder: hashing uses 384 by default,
    # text-embedding-3-small produces 1536.
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "384"))
    # Chunking: characters per chunk and overlap between chunks.
    chunk_chars: int = int(os.getenv("CHUNK_CHARS", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    # Reject single documents larger than this, in characters.
    max_document_chars: int = int(os.getenv("MAX_DOCUMENT_CHARS", "200000"))


settings = Settings()
