"""C1/C5: the faithfulness audit must catch poisoned or drifted plans."""

import pytest

from companion.models import Grade
from companion.rag.faithfulness import audit_plan
from companion.rag.poison import strip_poison


def _serials():
    return [
        {"id": "SN-4419", "lot_id": "L-8819", "status": "wip"},
        {"id": "SN-4420", "lot_id": "L-8819", "status": "wip"},
        {"id": "SN-4421", "lot_id": "L-8819", "status": "wip"},
        {"id": "SN-4422", "lot_id": "L-8819", "status": "shipped"},
    ]


def _clean_plan():
    return {
        "lot_id": "L-8819",
        "sop_ids": ["QMS-TORQUE-12"],
        "exceptions": [{"serial_id": "SN-4422", "kind": "shipped_escalate"}],
        "explanation": "Lot L-8819 requires a lot hold per QMS-TORQUE-12.",
    }


def _clean_grades():
    return [
        {"id": "QMS-TORQUE-12#action", "label": "relevant"},
        {"id": "QMS-TORQUE-11#action", "label": "wrong_rev"},
    ]


def test_clean_plan_passes_audit():
    assert audit_plan(_clean_plan(), _clean_grades(), _serials(), "L-8819") == []


def test_explanation_unknown_sop_is_caught():
    plan = _clean_plan()
    plan["explanation"] = "Lot L-8819 hold per QMS-TORQUE-11 and SN-4422."
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("QMS-TORQUE-11" in v and "kept evidence" in v for v in violations)


def test_explanation_unknown_lot_is_caught():
    plan = _clean_plan()
    plan["explanation"] = "Lot L-0000 requires a lot hold per QMS-TORQUE-12."
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("L-0000" in v and "kept evidence" in v for v in violations)


def test_explanation_unknown_serial_is_caught():
    plan = _clean_plan()
    plan["explanation"] = "Lot L-8819 per QMS-TORQUE-12. Exception SN-9999."
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("SN-9999" in v and "kept evidence" in v for v in violations)


def test_explanation_grounded_ids_pass():
    plan = _clean_plan()
    plan["explanation"] = (
        "Lot L-8819 requires a lot hold per QMS-TORQUE-12. Exceptions: SN-4422."
    )
    assert audit_plan(plan, _clean_grades(), _serials(), "L-8819") == []


def test_poison_citation_is_caught():
    plan = _clean_plan()
    plan["sop_ids"] = ["QMS-TORQUE-11"]  # obsolete rev cited
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("no surviving relevant chunk" in v for v in violations)


def test_lot_mismatch_is_caught():
    violations = audit_plan(_clean_plan(), _clean_grades(), _serials(), "L-9999")
    assert any("lot mismatch" in v for v in violations)


def test_shipped_serial_skipped_is_caught():
    plan = _clean_plan()
    plan["exceptions"] = []  # shipped serial silently dropped
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("exceptions" in v and "shipped serials" in v for v in violations)


def test_wip_as_exception_is_caught():
    plan = _clean_plan()
    plan["exceptions"] = [{"serial_id": "SN-4420", "kind": "shipped_escalate"}]
    violations = audit_plan(plan, _clean_grades(), _serials(), "L-8819")
    assert any("WIP serial" in v for v in violations)


# ------------------------------------------------------- poison strip (zero-good CAPA)

def _capa_chunk(doc_id: str, plant: str):
    from companion.models import Chunk

    return Chunk(
        chunk_id=f"{doc_id}#action",
        doc_id=doc_id,
        doc_stem=doc_id.rsplit("-", 1)[0],
        rev=1,
        effective_date="2019-01-01",
        plant=plant,
        doc_type="capa",
        heading="Action",
        text="torque containment lookalike",
    )


def test_strip_poison_with_zero_good_capa_keeps_nothing_but_does_not_crash():
    capa = [_capa_chunk("CAPA-2019-PLANT-A", "PA"), _capa_chunk("CAPA-2020-PLANT-B", "PB")]
    grades = [
        Grade(
            id="CAPA-2019-PLANT-A#action",
            label="wrong_plant",
            code_labels=["wrong_plant"],
        ),
        Grade(
            id="CAPA-2020-PLANT-B#action",
            label="wrong_plant",
            code_labels=["wrong_plant"],
        ),
    ]
    # every CAPA is wrong-plant poison -> kept set is empty; that is a PASS for
    # the graph (procedure-only evidence), never an abstain.
    kept, dropped = strip_poison(capa, grades)
    assert kept == []
    assert len(dropped) == 2
