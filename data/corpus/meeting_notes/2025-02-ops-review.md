---
title: Operations Review — February 2025
doc_type: meeting_notes
as_of: 2025-02-27
attendees: VP Operations, Customer Ops Lead, Inventory Ops Lead, Data Platform Lead
---

# Operations Review — February 27, 2025

## Refund backlog remediation

January's payments-queue backlog pushed average refund initiation to 63
hours against the 48-hour target. Backlog cleared February 10. Goodwill
store credits ($25 each) were issued on 41 affected tickets. Decision:
keep the temporary second payments worker until the v3 policy launch
settles, then reassess in the April review.

## Returns policy v3 readiness

Policy v3 goes live March 1, 2025. Key operational changes: 35-day
electronics window for Gold/Platinum, holiday extension to January 31,
electronics preference restocking fee down to 10%, and 24-hour store-credit
processing. Support macros and the returns portal copy were updated;
training completed for Tier 1 on February 20. Open risk: marketplace
listings still show the 2024 windows in two cached templates.

## Tablet calibration defect follow-through

Returns tied to the accelerometer calibration defect (supplier corrective
action CAPA-2024-091, filed September 2024) continue to arrive: 17 units in
January, 9 in February. Trend is declining as pre-fix inventory sells
through. Risk Operations agreed to exclude CAPA-linked returns from the
fraud counter after a false-positive hold in March was reviewed.

## Inventory checkpoint

West regional warehouse pick-error rate rose to 0.9% (target 0.5%),
driving wrong-item-shipped tickets. Root cause: bin re-slotting during the
January reset. Corrective re-labeling scheduled for the first week of March.
Sell-through on Electronics is tracking at 82% against the mid-cycle
checkpoint — below the 85% reorder-review trigger, so no early reorder.

## Actions

1. Customer Ops: purge cached marketplace templates showing 2024 windows.
2. Inventory Ops: complete West warehouse re-labeling by March 7.
3. Data Platform: add refund-initiation-hours to the daily ops digest.
4. All: review v3 launch metrics at the March ops review.
