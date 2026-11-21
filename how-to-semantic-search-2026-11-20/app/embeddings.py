"""Embedding providers.

An embedder turns text into a vector of floats. Two texts with similar
meaning produce vectors that point in a similar direction, which is
what makes search by meaning possible.

Two providers ship here:
- HashingEmbedder: deterministic, offline, no API key. It hashes word
  tokens into a fixed size vector. Good for local runs, CI and demos.
  It captures word overlap, not deep meaning.
- OpenAIEmbedder: calls the OpenAI embeddings API. Use this in
  production for real semantic quality.

Both return L2 normalised vectors, so cosine similarity is a plain
dot product in the store.
"""
import hashlib
import math
import re
import time

import httpx

TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Offline embedder based on signed feature hashing."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.model_name = f"hashing-{dim}"

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = TOKEN_RE.findall(text.lower())
        for tok in tokens:
            digest = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAIEmbedder:
    """Embedder backed by the OpenAI embeddings API, with retries."""

    API_URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai embedder")
        self.api_key = api_key
        self.model_name = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        # The API accepts batches; 100 texts per call is a safe size.
        for start in range(0, len(texts), 100):
            batch = texts[start : start + 100]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model_name, "input": batch},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                data.sort(key=lambda row: row["index"])
                return [row["embedding"] for row in data]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"embedding request failed: {last_error}")


def build_embedder(settings) -> HashingEmbedder | OpenAIEmbedder:
    if settings.embedder == "openai":
        return OpenAIEmbedder(settings.openai_api_key, settings.openai_model)
    return HashingEmbedder(settings.embedding_dim)
