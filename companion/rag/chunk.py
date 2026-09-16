from __future__ import annotations

import re
from pathlib import Path

from companion.models import Chunk


def index_text(chunk: Chunk) -> str:
    """Contextual prefix for BM25 and dense vectors only.

    Evidence, topic grading, and the plan still use ``chunk.text`` (raw body).
    """
    return (
        f"Plant {chunk.plant} · {chunk.doc_id} · rev {chunk.rev} · {chunk.heading}\n"
        f"{chunk.text}"
    )


HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "body"


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    text = raw.strip()
    if not text.startswith("---"):
        raise ValueError("corpus file missing frontmatter")
    _, fm, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in fm.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def chunk_markdown(path: Path) -> list[Chunk]:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    doc_id = meta["doc_id"]
    parts = HEADING_RE.split(body)
    chunks: list[Chunk] = []
    # parts: [preamble, heading1, body1, heading2, body2, ...]
    if parts[0].strip():
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#lead",
                doc_id=doc_id,
                doc_stem=meta["doc_stem"],
                rev=int(meta["rev"]),
                effective_date=meta["effective_date"],
                plant=meta["plant"],
                doc_type=meta["doc_type"],
                heading="lead",
                text=parts[0].strip(),
            )
        )
    rest = parts[1:]
    for i in range(0, len(rest), 2):
        heading = rest[i].strip()
        text = rest[i + 1].strip() if i + 1 < len(rest) else ""
        if not text:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#{_slug(heading)}",
                doc_id=doc_id,
                doc_stem=meta["doc_stem"],
                rev=int(meta["rev"]),
                effective_date=meta["effective_date"],
                plant=meta["plant"],
                doc_type=meta["doc_type"],
                heading=heading,
                text=text,
            )
        )
    return chunks


def load_corpus(corpus_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob("*.md")):
        chunks.extend(chunk_markdown(path))
    if not chunks:
        raise FileNotFoundError(f"no corpus markdown in {corpus_dir}")
    return chunks
