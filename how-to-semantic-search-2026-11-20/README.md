# Production Semantic Search Service

Companion code for the LinkedIn How-to guide "How to Build a Production
Semantic Search Service" by Eng. Mauro Tommasi (20 Nov 2026).
Guide: follow along on LinkedIn: linkedin.com/in/maurotommasi

A complete, runnable semantic search service: document ingestion,
chunking, embeddings, a vector store, and a search API. It runs locally
with zero external services, and switches to PostgreSQL + pgvector and
the OpenAI embeddings API in production with environment variables only.

## Quick start (local, offline)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
# in a second terminal:
python client_demo.py
```

The demo indexes five help centre documents from `sample_data.json`
and runs four searches. The correct document ranks first on each one.

## Production setup (pgvector + OpenAI embeddings)

```bash
docker run -d --name pgvector -e POSTGRES_USER=search \
  -e POSTGRES_PASSWORD=search -e POSTGRES_DB=search \
  -p 5432:5432 pgvector/pgvector:pg16
psql "postgresql://search:search@localhost:5432/search" -f schema.sql

export STORE_BACKEND=pgvector
export EMBEDDER=openai
export EMBEDDING_DIM=1536
export OPENAI_API_KEY=sk-...
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 4
```

Note: `EMBEDDING_DIM` and the `vector(N)` size in `schema.sql` must
match the embedder (384 for the hashing embedder, 1536 for
text-embedding-3-small).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /health | Status, embedder, store, chunk count |
| POST | /documents | Index or re-index one document |
| POST | /documents/bulk | Index up to 1000 documents |
| POST | /search | Search: query, top_k, metadata filters |
| DELETE | /documents/{id} | Remove a document and its chunks |
| GET | /stats | Chunk count and embedder |

## Layout

- `app/config.py` environment based settings
- `app/embeddings.py` hashing embedder (offline) and OpenAI embedder
- `app/text.py` chunking with overlap
- `app/store.py` in-memory store and pgvector store
- `app/models.py` request and response schemas
- `app/main.py` FastAPI application and endpoints
- `schema.sql` PostgreSQL + pgvector schema and HNSW index
- `client_demo.py` indexing and search demo
- `sample_data.json` five example documents
