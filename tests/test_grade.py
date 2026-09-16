from companion.models import Chunk
from companion.mom.db import connect, seed, current_rev_lookup, publish_torque_rev
from companion.rag.grade import grade_chunks
from companion.rag.poison import strip_poison


def _chunk(**kwargs) -> Chunk:
    base = dict(
        chunk_id="x#action",
        doc_id="X",
        doc_stem="QMS-TORQUE",
        rev=12,
        effective_date="2026-01-15",
        plant="B",
        doc_type="qms",
        heading="Action",
        text="lot hold",
    )
    base.update(kwargs)
    return Chunk(**base)


def test_code_grade_marks_obsolete_rev_and_other_plant():
    conn = connect(":memory:")
    seed(conn)
    current = current_rev_lookup(conn)
    chunks = [
        _chunk(chunk_id="QMS-TORQUE-12#action", doc_id="QMS-TORQUE-12", rev=12),
        _chunk(chunk_id="QMS-TORQUE-11#action", doc_id="QMS-TORQUE-11", rev=11),
        _chunk(chunk_id="QMS-TORQUE-13#action", doc_id="QMS-TORQUE-13", rev=13),
        _chunk(
            chunk_id="CAPA-2019-PLANT-A#action",
            doc_id="CAPA-2019-PLANT-A",
            doc_stem="CAPA-TORQUE",
            rev=1,
            plant="A",
            doc_type="capa",
        ),
    ]
    llm = {c.chunk_id: "relevant" for c in chunks}
    grades = grade_chunks(chunks, "B", current, llm)
    by_id = {g.id: g.label for g in grades}
    assert by_id["QMS-TORQUE-12#action"] == "relevant"
    assert by_id["QMS-TORQUE-11#action"] == "wrong_rev"
    assert by_id["QMS-TORQUE-13#action"] == "wrong_rev"
    assert by_id["CAPA-2019-PLANT-A#action"] == "wrong_plant"


def test_wrong_rev_is_pointer_mismatch_not_older():
    conn = connect(":memory:")
    seed(conn)
    publish_torque_rev(conn)
    current = current_rev_lookup(conn)
    chunks = [
        _chunk(chunk_id="QMS-TORQUE-12#action", doc_id="QMS-TORQUE-12", rev=12),
        _chunk(chunk_id="QMS-TORQUE-13#action", doc_id="QMS-TORQUE-13", rev=13),
    ]
    llm = {c.chunk_id: "relevant" for c in chunks}
    grades = grade_chunks(chunks, "B", current, llm)
    by_id = {g.id: g.label for g in grades}
    assert by_id["QMS-TORQUE-13#action"] == "relevant"
    assert by_id["QMS-TORQUE-12#action"] == "wrong_rev"


def test_poison_strip_drops_plant_a_from_citations():
    capa = _chunk(
        chunk_id="CAPA-2019-PLANT-A#action",
        doc_id="CAPA-2019-PLANT-A",
        doc_stem="CAPA-TORQUE",
        plant="A",
        doc_type="capa",
        rev=1,
    )
    good = _chunk(
        chunk_id="CAPA-2024-TORQUE#action",
        doc_id="CAPA-2024-TORQUE",
        doc_stem="CAPA-TORQUE",
        doc_type="capa",
        rev=3,
    )
    conn = connect(":memory:")
    seed(conn)
    grades = grade_chunks(
        [capa, good],
        "B",
        current_rev_lookup(conn),
        {capa.chunk_id: "relevant", good.chunk_id: "relevant"},
    )
    kept, dropped = strip_poison([capa, good], grades)
    assert capa.chunk_id in dropped
    assert all(c.doc_id != "CAPA-2019-PLANT-A" for c in kept)
