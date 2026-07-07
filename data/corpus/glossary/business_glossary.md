---
title: NexusIQ Business Glossary
doc_type: glossary
as_of: 2025-01-15
owner: Data Governance Council
---

# NexusIQ Business Glossary

Canonical metric and term definitions for NexusIQ analytics. When a report
disagrees with this glossary, the glossary wins. Maintained by the Data
Governance Council; changes require a data-contract review.

## Net Revenue

Net revenue is the sum of `sales_transactions.total_amount` minus refunded
amounts for returns with status refunded or approved. Alias: net sales,
revenue after refunds. Plain "revenue" in dashboards means gross revenue
unless the report explicitly says net.

## Gross Revenue

Gross revenue is the sum of `sales_transactions.total_amount` before
subtracting any refunds. Alias: gross sales.

## Return Rate

Return rate is the count of returns divided by the count of completed
transactions in the same period, expressed as a percentage. FY 2024
company-wide return rate was 5.7% (5,685 returns against 100,000
transactions).

## Average Order Value (AOV)

Average order value is gross revenue divided by the number of completed
transactions in the period. AOV is reported per category and per region;
the company-wide figure is only used in executive summaries.

## Active Customer

An active customer has at least one completed purchase in the trailing
6 months. Customers with only cancelled or fully-refunded orders in the
window do not count as active.

## Churned Customer

A churned customer purchased in H1 2024 but has no completed purchase after
July 1, 2024. Churn is evaluated monthly against the trailing window, not
against calendar quarters.

## Loyalty Tiers

Bronze, Silver, Gold, Platinum. Gold and above unlock receipt-free returns
via account lookup and the extended electronics return window defined in the
Returns and Refunds Policy v3 (effective March 1, 2025).

## Sell-Through Rate

Units sold divided by units received in the same period, per SKU. Used by
Inventory Operations to trigger reorder review when sell-through exceeds 85%
before the mid-cycle checkpoint.
