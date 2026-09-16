"""Scenario pack: ten canned incidents the console can run end to end.

Every expectation below was validated against the local provider pipeline
(hybrid retrieve -> grade -> conditional route) before being written down;
the eval runner replays them on throwaway databases so drift fails loudly.

Two scenarios exercise the refusal route (garbage/off-topic -> rewrite loop ->
abstain), eight exercise the full approve path (retrieve -> grade ->
retrieve_capa -> strip_poison -> plan -> audit -> interrupt). Three run on
lots other than the hero lot so nothing in the demo is hardcoded to L-8819.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Scenario(BaseModel):
    id: str
    label: str
    query: str
    expect_status: Literal["waiting_human", "abstained"]
    # One line for the UI: which route this takes and why the graph routes it there.
    why_route: str
    lot_id: str | None = None  # None -> the default demo lot (L-8819)
    must_cite: list[str] = Field(default_factory=list)
    must_not_cite: list[str] = Field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in [
        Scenario(
            id="torque_ncr",
            label="Torque NCR (hero)",
            query=(
                "SN-4419 failed torque. What does current procedure require, "
                "and what should we hold?"
            ),
            expect_status="waiting_human",
            why_route=(
                "This straightforward path finds current Plant B evidence, proposes "
                "containment, then pauses for your decision."
            ),
            must_cite=["QMS-TORQUE-12"],
            must_not_cite=["QMS-TORQUE-11", "QMS-TORQUE-13", "CAPA-2019-PLANT-A", "WI-UNRELATED"],
        ),
        Scenario(
            id="obsolete_rev_lure",
            label="Obsolete revision lure",
            query=(
                "SN-4419 failed torque. The old instruction said hold each "
                "serial individually and start rework right away. What should "
                "we do now?"
            ),
            expect_status="waiting_human",
            why_route=(
                "Worded to bait the superseded rev 11; grading must retrieve "
                "and then void it before anything is planned."
            ),
            must_cite=["QMS-TORQUE-12"],
            must_not_cite=["QMS-TORQUE-11", "QMS-TORQUE-13"],
        ),
        Scenario(
            id="wrong_plant_capa",
            label="Wrong-plant CAPA lure",
            query=(
                "We had a similar torque escape handled at Plant A in 2019. "
                "Which corrective action applies to our Plant B torque NCR "
                "today, and what should we hold?"
            ),
            expect_status="waiting_human",
            why_route=(
                "CAPA search deliberately runs with the plant filter off, so "
                "the Plant A lookalike surfaces and code rejects it."
            ),
            must_cite=["QMS-TORQUE-12"],
            must_not_cite=["CAPA-2019-PLANT-A", "QMS-TORQUE-13"],
        ),
        Scenario(
            id="containment_scope",
            label="Lot vs unit scope",
            query=(
                "After the torque failure on serial SN-4419, should we hold "
                "every unit in the batch or just the failed one? What does the "
                "current procedure require?"
            ),
            expect_status="waiting_human",
            why_route=(
                "Asks the grain question; the plan must hold the lot, not "
                "carve per-serial rows."
            ),
            must_cite=["QMS-CONTAINMENT-05"],
            must_not_cite=["WI-UNRELATED"],
        ),
        Scenario(
            id="shipped_sibling",
            label="Shipped-sibling exception",
            query=(
                "One unit already shipped before this torque failure on "
                "SN-4419. What does the current shipping hold procedure "
                "require for its siblings still in the plant?"
            ),
            expect_status="waiting_human",
            why_route=(
                "The escaped unit becomes an escalate exception, never a hold "
                "row — MES status decides, not the model."
            ),
            must_cite=["QMS-SHIP-HOLD-02"],
            must_not_cite=["WI-UNRELATED"],
        ),
        Scenario(
            id="calibration_escape",
            label="Wrench out of calibration",
            query=(
                "The torque wrench used on serial SN-4419 is past its "
                "calibration due date. What does the current torque procedure "
                "require us to do?"
            ),
            expect_status="waiting_human",
            why_route=(
                "Runs on lot L-8820: same graph, different MOM rows, so the "
                "plan and exceptions come from data, not defaults."
            ),
            lot_id="L-8820",
            must_cite=["QMS-CALIBRATION-09"],
            must_not_cite=["QMS-TORQUE-11"],
        ),
        Scenario(
            id="skipped_verification",
            label="Skipped verification step",
            query=(
                "An operator skipped the re-torque verification step in "
                "WI-TORQUE during final assembly of SN-4419. What does the "
                "current work instruction require now?"
            ),
            expect_status="waiting_human",
            why_route=(
                "A work-instruction escape on lot L-8830; citations must lead "
                "with the WI itself."
            ),
            lot_id="L-8830",
            must_cite=["WI-TORQUE-08"],
            must_not_cite=["CAPA-2019-PLANT-A"],
        ),
        Scenario(
            id="customer_complaint",
            label="Customer complaint NCR",
            query=(
                "A customer complained about loose fasteners on a delivered "
                "unit. Which NCR handling procedure applies, and what do we "
                "hold?"
            ),
            expect_status="waiting_human",
            why_route=(
                "Complaint-origin NCR on lot L-8821 routes through the NCR "
                "handling SOP."
            ),
            lot_id="L-8821",
            must_cite=["QMS-NCR-HANDLING-03"],
            must_not_cite=["CAPA-2019-PLANT-A"],
        ),
        Scenario(
            id="garbage_query",
            label="Garbage query",
            query="How do I change the default printer on macOS Sequoia?",
            expect_status="abstained",
            why_route=(
                "Nothing grounds, so the grade junction sends it into the "
                "one-shot rewrite loop, then to refuse."
            ),
        ),
        Scenario(
            id="off_topic_refusal",
            label="Off-topic refusal",
            query="Where can I find the cafeteria menu and the guest wifi password?",
            expect_status="abstained",
            why_route=(
                "Zero procedure overlap: the graph refuses without a write — "
                "refusing is a feature."
            ),
        ),
    ]
}

SCENARIO_ORDER = [
    "torque_ncr",
    "obsolete_rev_lure",
    "wrong_plant_capa",
    "containment_scope",
    "shipped_sibling",
    "calibration_escape",
    "skipped_verification",
    "customer_complaint",
    "garbage_query",
    "off_topic_refusal",
]


def get_scenario(scenario_id: str | None) -> Scenario | None:
    if not scenario_id:
        return None
    return SCENARIOS.get(scenario_id)


def list_scenarios() -> list[Scenario]:
    """Registry order = demo order (hero first, refusals last)."""
    return [SCENARIOS[sid] for sid in SCENARIO_ORDER]
