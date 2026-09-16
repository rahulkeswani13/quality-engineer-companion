from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HoldException(BaseModel):
    serial_id: str
    kind: Literal["shipped_escalate"] = "shipped_escalate"


class ContainmentPlan(BaseModel):
    lot_id: str
    sop_ids: list[str] = Field(default_factory=list)
    exceptions: list[HoldException] = Field(default_factory=list)
    explanation: str = ""


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_stem: str
    rev: int
    effective_date: str
    plant: str
    doc_type: str
    heading: str
    text: str


class Grade(BaseModel):
    id: str
    label: Literal["relevant", "off_topic", "wrong_rev", "wrong_plant"]
    llm_label: Literal["relevant", "off_topic"] | None = None
    code_labels: list[str] = Field(default_factory=list)
