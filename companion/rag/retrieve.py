from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from rank_bm25 import BM25Okapi

from companion.models import Chunk
from companion.rag.chunk import index_text
from companion.rag.embed import (
    LOCAL_RETRIEVER,
    embed_corpus,
    gemini_embed_query,
    hashed_embed,
)

RRF_K = 60


@dataclass
class HybridIndex:
    chunks: list[Chunk]
    vectors: np.ndarray
    bm25: BM25Okapi
    tokenized: list[list[str]] = field(repr=False)
    retriever: str = LOCAL_RETRIEVER

    def by_id(self, chunk_id: str) -> Chunk:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise KeyError(chunk_id)


def tokenize(text: str) -> list[str]:
    return [t for t in text.lower().replace("#", " ").replace("/", " ").split() if t]


def build_index(
    chunks: list[Chunk],
    vectors: np.ndarray | None = None,
    *,
    provider: str | None = None,
    cache_path: str | None = None,
) -> HybridIndex:
    texts = [index_text(c) for c in chunks]
    tokenized = [tokenize(t) for t in texts]
    if vectors is None:
        vectors, retriever, _hit = embed_corpus(
            texts,
            provider=provider or os.environ.get("COMPANION_PROVIDER", "local"),
            cache_path=cache_path,
        )
    else:
        # Explicit vectors (tests / prebuilt): infer the space they came from.
        retriever = os.environ.get("COMPANION_EMBEDDER", LOCAL_RETRIEVER)
        if provider == "gemini":
            retriever = "gemini-embedding-2"
    return HybridIndex(
        chunks=chunks,
        vectors=vectors,
        bm25=BM25Okapi(tokenized),
        retriever=retriever,
        tokenized=tokenized,
    )


def _rrf(rank_lists: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, idx in enumerate(ranks, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return scores


def _cosine_ranks(index: HybridIndex, query_vec: np.ndarray, mask: list[int], topn: int) -> list[int]:
    if not mask:
        return []
    mat = index.vectors[mask]
    sims = mat @ query_vec
    order = np.argsort(-sims)[:topn]
    return [mask[i] for i in order]


def _bm25_ranks(index: HybridIndex, query: str, mask: list[int], topn: int) -> list[int]:
    if not mask:
        return []
    scores = index.bm25.get_scores(tokenize(query))
    ranked = sorted(mask, key=lambda i: scores[i], reverse=True)[:topn]
    return ranked


def _overlap_rerank(query: str, chunks: list[Chunk]) -> list[Chunk]:
    q = set(tokenize(query))
    def score(chunk: Chunk) -> int:
        return len(q & set(tokenize(index_text(chunk))))
    return sorted(chunks, key=score, reverse=True)


# ------------------------------------------------------------------ reranker
# One process-wide cross-encoder (A3). Loading ms-marco-MiniLM takes seconds;
# doing it per retrieve() call was the reason it shipped default-off.

_CROSS_ENCODER: "_CrossEncoderLike | None" = None
_CROSS_ENCODER_TRIED = False


class _CrossEncoderLike:
    """Structural stand-in for sentence_transformers.CrossEncoder (optional dep)."""

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        raise NotImplementedError


def _rerank_enabled() -> bool:
    return os.environ.get("COMPANION_RERANK", "1").strip().lower() not in {"0", "false", "no", "off"}


def get_cross_encoder():
    global _CROSS_ENCODER, _CROSS_ENCODER_TRIED
    if not _rerank_enabled():
        return None
    if not _CROSS_ENCODER_TRIED:
        _CROSS_ENCODER_TRIED = True
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

            _CROSS_ENCODER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception:  # noqa: BLE001 — optional dep; overlap rerank remains
            _CROSS_ENCODER = None
            print("[companion] sentence-transformers unavailable; using overlap rerank")
    return _CROSS_ENCODER


def reset_cross_encoder() -> None:
    """Test hook so the load-once behaviour stays assertable."""
    global _CROSS_ENCODER, _CROSS_ENCODER_TRIED
    _CROSS_ENCODER = None
    _CROSS_ENCODER_TRIED = False


def retrieve(
    index: HybridIndex,
    query: str,
    *,
    plant: str | None,
    doc_types: set[str],
    top_rrf: int = 8,
    top_k: int = 8,
    query_vec: np.ndarray | None = None,
) -> list[Chunk]:
    mask = []
    for i, chunk in enumerate(index.chunks):
        if chunk.doc_type not in doc_types:
            continue
        if plant is not None and chunk.plant != plant:
            continue
        mask.append(i)
    if query_vec is not None:
        qvec = query_vec
    elif index.retriever != LOCAL_RETRIEVER:
        try:
            qvec = gemini_embed_query(query)
        except Exception:  # noqa: BLE001 — degrade to local space, never crash a run
            qvec = hashed_embed(query)
    else:
        qvec = hashed_embed(query)
    dense = _cosine_ranks(index, qvec, mask, top_rrf)
    sparse = _bm25_ranks(index, query, mask, top_rrf)
    fused = _rrf([dense, sparse])
    ordered_idx = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_rrf]
    ranked = [index.chunks[i] for i in ordered_idx]
    reranked = _overlap_rerank(query, ranked)
    encoder = get_cross_encoder()
    if encoder is not None:
        pairs = [(query, index_text(c)) for c in reranked]
        try:
            scores = encoder.predict(pairs)
            reranked = [
                c for _, c in sorted(zip(scores, reranked), key=lambda x: x[0], reverse=True)
            ]
        except Exception:  # noqa: BLE001 — rerank failure must not fail retrieval
            pass
    return reranked[:top_k]
