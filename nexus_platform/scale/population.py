"""Generated employee population — 100-150 login-capable employees/company.

The backend carries the full generated population (org structure, role,
access policy, credentials); the login UI shows only the curated demo
accounts. Passwords follow a deterministic prototype rule
(gen-<slug>-<n>) so the load-test harness can authenticate without storing
any secret; only the salted hash is persisted.

Usage:
    python -m nexus_platform.scale.population [slug ...]
"""

from __future__ import annotations

import random
import sys

from nexus_platform import store
from nexus_platform.registry import get_registry, hash_password

FIRST = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Kai", "Iris", "Leo", "Nina",
         "Omar", "Priya", "Sam", "Tara", "Yuki", "Diego", "Elena", "Femi",
         "Grace", "Hugo", "Anya", "Ravi", "Sofia", "Mateo", "Lena", "Jonas",
         "Aisha", "Marco", "Ines", "Tom", "Wei"]
LAST = ["Chen", "Patel", "Kim", "Garcia", "Okafor", "Novak", "Silva",
        "Haddad", "Larsen", "Mori", "Ivanov", "Dubois", "Nakamura", "Osei",
        "Reyes", "Kowalski", "Berg", "Costa", "Ahmed", "Fischer"]

# Department → (platform role, title template, weight)
DEPT_ROLES = [
    ("Engineering", "Ops", "Software Engineer", 5),
    ("Sales", "Analyst", "Account Executive", 3),
    ("Marketing", "Analyst", "Growth Marketer", 2),
    ("Support", "Support", "Support Specialist", 3),
    ("Finance", "Finance", "Financial Analyst", 2),
    ("People", "HR", "People Partner", 1),
    ("Operations", "Ops", "Operations Analyst", 2),
    ("Product", "Analyst", "Product Analyst", 2),
]


def generated_password(slug: str, n: int) -> str:
    """Deterministic prototype credential rule for generated employees."""
    return f"gen-{slug}-{n}"


def generate_population(slug: str) -> list[dict]:
    registry = get_registry()
    company = registry.get_company(slug)
    if company is None:
        raise KeyError(f"Unknown company: {slug}")
    rng = random.Random(hash(slug) % 100_000 + 7)
    n_emps = 100 + rng.randint(0, 50)

    curated = {e.email for e in registry.company_employees(slug)}
    employees: list[dict] = []
    managers: dict[str, str] = {}
    for i in range(1, n_emps + 1):
        dept, role, title, _ = rng.choices(
            DEPT_ROLES, weights=[w for *_, w in DEPT_ROLES])[0]
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first.lower()}.{last.lower()}{i}@{company.domain}"
        if email in curated:
            continue
        team = f"{dept} Team {rng.randint(1, 3)}"
        if team not in managers:
            managers[team] = email
        employees.append({
            "email": email,
            "company": slug,
            "name": f"{first} {last}",
            "role": role,
            "title": title if i % 9 else f"{dept} Manager",
            "department": dept,
            "team": team,
            "manager_email": managers[team],
            "password_hash": hash_password(generated_password(slug, i)),
        })
    return employees


def seed_population(slug: str) -> int:
    return store.replace_generated_employees(slug, generate_population(slug))


if __name__ == "__main__":
    slugs = sys.argv[1:] or [c.slug for c in get_registry().companies.values()]
    for s in slugs:
        print(f"{s}: {seed_population(s)} generated employees")
