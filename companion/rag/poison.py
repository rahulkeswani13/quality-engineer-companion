from __future__ import annotations

from companion.models import Chunk, Grade

POISON_LABELS = {"wrong_plant", "wrong_rev"}


def strip_poison(
    chunks: list[Chunk],
    grades: list[Grade],
) -> tuple[list[Chunk], list[str]]:
    """Drop poison CAPA from citation set. Grades stay visible. Empty good-CAPA still proceeds."""
    poison_ids = {g.id for g in grades if g.label in POISON_LABELS or set(g.code_labels) & POISON_LABELS}
    kept = [c for c in chunks if c.chunk_id not in poison_ids]
    dropped = [c.chunk_id for c in chunks if c.chunk_id in poison_ids]
    return kept, dropped


def sop_ids_from_chunks(chunks: list[Chunk]) -> list[str]:
    seen: list[str] = []
    for chunk in chunks:
        if chunk.doc_id not in seen:
            seen.append(chunk.doc_id)
    return seen
