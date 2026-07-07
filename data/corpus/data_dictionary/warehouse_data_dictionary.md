---
title: NexusIQ Warehouse Data Dictionary
doc_type: data_dictionary
as_of: 2025-01-10
owner: Data Platform Team
---

# NexusIQ Warehouse Data Dictionary

Column-level documentation for the operational tables behind NexusIQ
analytics. Types reflect the PostgreSQL source of truth.

## Table: sales_transactions

One row per completed line-item sale. Grain: transaction.

| Column | Type | Description |
|---|---|---|
| transaction_id | text, PK | Unique transaction identifier |
| transaction_date | date | Date the sale completed |
| product_name | text | Product sold (e.g. Laptop, Jeans, Bedding) |
| category | text | One of: Electronics, Clothing, Home, Sports, Food |
| region | text | Sales region: North, South, East, West |
| quantity | integer | Units in the transaction |
| unit_price | numeric | Price per unit at time of sale, USD |
| total_amount | numeric | quantity × unit_price, USD; feeds gross revenue |
| payment_method | text | Credit Card, Debit Card, PayPal, Gift Card, Cash |
| customer_id | text | Purchasing customer; joins to customers |

Notes: `total_amount` is the only revenue column; gross revenue sums it
directly, net revenue subtracts refunded returns (see Business Glossary).

## Table: returns

One row per return request. Grain: return.

| Column | Type | Description |
|---|---|---|
| return_id | text, PK | Unique return identifier |
| transaction_id | text, FK | Original sale; joins to sales_transactions |
| return_date | date | Date the return was requested |
| refund_amount | numeric | USD amount refunded when status is refunded |
| status | text | pending, received, approved, refunded, rejected |
| reason | text | Defective, Not As Described, Wrong Item, Size/Fit, Preference |

Notes: only refunded and approved statuses subtract from net revenue.
FY 2024 held 5,685 return rows.

## Table: customers

| Column | Type | Description |
|---|---|---|
| customer_id | text, PK | Unique customer identifier |
| join_date | date | Account creation date |
| loyalty_tier | text | Bronze, Silver, Gold, Platinum |
| region | text | Home region, same domain as sales region |

## Freshness and contracts

sales_transactions loads nightly at 02:00 UTC; returns loads hourly.
A data contract asserts non-null transaction_id, non-negative amounts, and
category membership in the five allowed values; violations quarantine the
batch instead of loading it.
