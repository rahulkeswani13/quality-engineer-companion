---
doc_id: QMS-CONTAINMENT-05
doc_stem: QMS-CONTAINMENT
rev: 5
effective_date: 2025-09-01
plant: B
doc_type: qms
---
# QMS-CONTAINMENT-05

## Purpose
Current containment policy: lot is the hold grain unless a serial is already shipped.

## Trigger
Any quality escape on a lot with mixed WIP and shipped serials.

## Action
Lot hold plus shipped_escalate exception. Never apply_hold on a shipped serial as WIP.

## Authority
QE.
