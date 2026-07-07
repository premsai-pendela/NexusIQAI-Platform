"""Demo company + employee registry.

Prototype auth source of truth. Passwords are salted-hash of demo passwords —
honest prototype login, not production SSO. Employees belong to exactly one
company; the company is always inferred from the employee record, never from
client input.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SEED_PATH = Path(__file__).parent / "seed" / "employees.json"
_SALT = "nexusiq-platform-demo"  # demo-grade; documented as prototype


@dataclass(frozen=True)
class Company:
    slug: str
    name: str
    domain: str
    industry: str
    description: str


@dataclass(frozen=True)
class Employee:
    email: str
    name: str
    company_slug: str
    role: str
    password_hash: str
    title: str

    @property
    def is_admin(self) -> bool:
        return self.role in ("Admin", "CEO")


def hash_password(password: str) -> str:
    return hashlib.sha256(f"{_SALT}:{password}".encode()).hexdigest()


class Registry:
    def __init__(self, seed_path: Path = SEED_PATH):
        data = json.loads(seed_path.read_text())
        self.companies: dict[str, Company] = {
            c["slug"]: Company(**c) for c in data["companies"]
        }
        self.employees: dict[str, Employee] = {}
        for e in data["employees"]:
            record = Employee(
                email=e["email"].lower(),
                name=e["name"],
                company_slug=e["company_slug"],
                role=e["role"],
                password_hash=hash_password(e["password"]),
                title=e["title"],
            )
            if record.company_slug not in self.companies:
                raise ValueError(f"Employee {record.email} references unknown company")
            self.employees[record.email] = record

    def _generated(self, email: str) -> Optional[Employee]:
        """Generated (non-demo) population — backend scale, not shown in the
        login UI. Stored in the platform DB by scale.population."""
        from nexus_platform import store
        row = store.get_generated_employee(email)
        if row is None:
            return None
        return Employee(
            email=row["email"], name=row["name"],
            company_slug=row["company"], role=row["role"],
            password_hash=row["password_hash"], title=row["title"],
        )

    def authenticate(self, email: str, password: str) -> Optional[Employee]:
        emp = self.get_employee(email)
        if emp and emp.password_hash == hash_password(password):
            return emp
        return None

    def get_employee(self, email: str) -> Optional[Employee]:
        key = email.strip().lower()
        return self.employees.get(key) or self._generated(key)

    def get_company(self, slug: str) -> Optional[Company]:
        return self.companies.get(slug)

    def company_employees(self, slug: str) -> list[Employee]:
        return [e for e in self.employees.values() if e.company_slug == slug]


_registry: Optional[Registry] = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry
