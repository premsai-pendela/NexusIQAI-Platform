# MedCore Systems — Data Dictionary

## orders
order_id, order_date (2024), customer_id, product_id, region, quantity,
unit_price, total_amount, status (completed / refunded / pending).

## customers
customer_id, name, segment (Startup / Mid-Market / Enterprise), region,
signup_date, plan, mrr.

## products
product_id, name, category, list_price, launched.

## invoices
invoice_id, customer_id, issue_date, due_date, amount,
status (paid / overdue / open), paid_date.

## support_tickets
ticket_id, created_at, customer_id, category (billing / bug / how-to /
integration / outage), priority (low / medium / high / urgent),
status (resolved / open / escalated), resolution_hours, csat (1-5).

## employees_hr (restricted: HR and Admin/CEO roles only)
emp_id, department, role_title, region, hire_date, termination_date,
salary_band (B1-B5).
