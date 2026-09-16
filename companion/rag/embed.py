from __future__ import annotations

import hashlib
import os
import re

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

LOCAL_RETRIEVER = "local_hash_fallback"
GEMINI_RETRIEVER = "gemini-embedding-2"


class GeminiQuotaError(RuntimeError):
    def __init__(self, message: str = "gemini_429"):
        super().__init__(message)


# --------------------------------------------------------------------- local


def hashed_embed(text: str, dim: int = 96) -> np.ndarray:
    """Token-hash bag-of-words vector. Deterministic, offline, NOT a neural
    embedding — kept as the honest fallback when no GOOGLE_API_KEY is set."""
    vec = np.zeros(dim, dtype=np.float32)
    for tok in TOKEN_RE.findall(text.lower()):
        digest = hashlib.md5(tok.encode()).hexdigest()
        vec[int(digest, 16) % dim] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def hashed_embed_many(texts: list[str], dim: int = 96) -> np.ndarray:
    return np.vstack([hashed_embed(t, dim) for t in texts])


# -------------------------------------------------------------------- gemini


def _client():
    from google import genai

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiQuotaError("gemini_missing_key")
    return genai.Client(api_key=api_key)


def _is_quota_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "429" in text or "resourceexhausted" in name or "quota" in text


def gemini_embed_many(texts: list[str], model: str = GEMINI_RETRIEVER) -> np.ndarray:
    client = _client()
    try:
        result = client.models.embed_content(model=model, contents=texts)
    except Exception as exc:  # noqa: BLE001 — map vendor errors
        if _is_quota_error(exc):
            raise GeminiQuotaError("gemini_429") from exc
        raise
    vectors = []
    embeddings = getattr(result, "embeddings", None) or []
    for item in embeddings:
        values = getattr(item, "values", None)
        if values is None and isinstance(item, dict):
            values = item.get("values")
        vectors.append(np.asarray(values, dtype=np.float32))
    stacked = np.vstack(vectors)
    norms = np.linalg.norm(stacked, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return stacked / norms


def gemini_embed_query(text: str, model: str = GEMINI_RETRIEVER) -> np.ndarray:
    """Embed one query into the SAME space as gemini_embed_many."""
    return gemini_embed_many([text], model=model)[0]


# --------------------------------------------------------------------- cache


def corpus_hash(texts: list[str]) -> str:
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def load_vector_cache(cache_path: os.PathLike | str, expected_hash: str):
    """Return cached (vectors, retriever_name) if the corpus hash matches."""
    path = os.fspath(cache_path)
    if not os.path.exists(path):
        return None
    try:
        blob = np.load(path, allow_pickle=False)
    except (OSError, ValueError):
        return None
    if str(blob.get("corpus_hash", "")) != expected_hash:
        return None
    return np.asarray(blob["vectors"], dtype=np.float32), str(blob["retriever"])


def save_vector_cache(
    cache_path: os.PathLike | str,
    vectors: np.ndarray,
    retriever: str,
    expected_hash: str,
) -> None:
    parent = os.path.dirname(os.fspath(cache_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    np.savez(
        os.fspath(cache_path),
        vectors=vectors,
        retriever=np.asarray(retriever),
        corpus_hash=np.asarray(expected_hash),
    )


def embed_corpus(
    texts: list[str],
    *,
    provider: str,
    cache_path: os.PathLike | str | None = None,
):
    """Vectors the whole index should use, plus the truth about which embedder ran.

    Order: valid disk cache → Gemini (when provider=gemini and key present) →
    deterministic local hash fallback. Never half-fails mid-corpus: any Gemini
    failure falls back wholesale so vectors stay in ONE space per index build.
    """
    expected = corpus_hash(texts)

    if cache_path is not None:
        cached = load_vector_cache(cache_path, expected)
        if cached is not None:
            vectors, retriever = cached
            return vectors, retriever, True  # cache_hit=True

    if provider == "gemini":
        try:
            vectors = gemini_embed_many(texts)
            retriever = GEMINI_RETRIEVER
            if cache_path is not None:
                save_vector_cache(cache_path, vectors, retriever, expected)
            return vectors, retriever, False
        except GeminiQuotaError as exc:
            print(f"[companion] embeddings unavailable ({exc}); using {LOCAL_RETRIEVER}")
        except Exception as exc:  # noqa: BLE001 — any vendor error degrades cleanly
            print(f"[companion] embeddings failed ({exc}); using {LOCAL_RETRIEVER}")

    return hashed_embed_many(texts), LOCAL_RETRIEVER, False
