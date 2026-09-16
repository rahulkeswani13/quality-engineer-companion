from __future__ import annotations

from companion.models import Chunk, Grade

PROCEDURE_TYPES = {"qms", "wi"}


def code_labels(chunk: Chunk, plant: str, current_revs: dict[tuple[str, str], int]) -> list[str]:
    labels: list[str] = []
    if chunk.plant != plant:
        labels.append("wrong_plant")
    current = current_revs.get((chunk.doc_stem, plant))
    if current is not None and chunk.rev != current:
        labels.append("wrong_rev")
    return labels


def display_label(code: list[str], llm_label: str) -> str:
    if "wrong_rev" in code:
        return "wrong_rev"
    if "wrong_plant" in code:
        return "wrong_plant"
    return llm_label


def grade_chunks(
    chunks: list[Chunk],
    plant: str,
    current_revs: dict[tuple[str, str], int],
    llm_labels: dict[str, str],
) -> list[Grade]:
    grades: list[Grade] = []
    for chunk in chunks:
        code = code_labels(chunk, plant, current_revs)
        llm = llm_labels.get(chunk.chunk_id, "off_topic")
        grades.append(
            Grade(
                id=chunk.chunk_id,
                label=display_label(code, llm),  # type: ignore[arg-type]
                llm_label=llm,  # type: ignore[arg-type]
                code_labels=code,
            )
        )
    return grades


def passing_procedure(grades: list[Grade], chunks: list[Chunk]) -> list[Chunk]:
    by_id = {c.chunk_id: c for c in chunks}
    kept: list[Chunk] = []
    for grade in grades:
        chunk = by_id.get(grade.id)
        if chunk is None or chunk.doc_type not in PROCEDURE_TYPES:
            continue
        if grade.llm_label == "relevant" and "wrong_rev" not in grade.code_labels:
            kept.append(chunk)
    return kept
