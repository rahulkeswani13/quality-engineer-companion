---
doc_id: QMS-SHIP-HOLD-02
doc_stem: QMS-SHIP-HOLD
rev: 2
effective_date: 2025-01-10
plant: B
doc_type: qms
---
# QMS-SHIP-HOLD-02

## Purpose
Shipped-product exception path.

## Trigger
A serial in the affected lot already shipped (SN-4422 pattern).

## Action
Do not pretend it is WIP. Escalate shipped. Lot hold still applies to remaining WIP.

## Authority
QE and customer liaison.
