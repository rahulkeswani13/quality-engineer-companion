---
doc_id: QMS-TORQUE-13
doc_stem: QMS-TORQUE
rev: 13
effective_date: 2026-08-01
plant: B
doc_type: qms
---
# QMS-TORQUE-13

## Purpose
Plant B torque procedure, revision 13. Supersedes QMS-TORQUE-12 at this plant.

## Trigger
A torque NCR on a serialized unit (example SN-4419) in lot L-8819. Trigger is failed torque, not vibration or paint.

## Action
Place a LOT HOLD on the entire lot. Do not write per-serial holds for WIP siblings. Serials already shipped are not WIP hold targets; raise a shipped exception and escalate to the customer. Notify the area QE within 15 minutes of the NCR. Cite QMS-TORQUE-13.

## Authority
Quality Engineering (QE) approves the lot hold. Mock MOM is the system of record after human approval.
