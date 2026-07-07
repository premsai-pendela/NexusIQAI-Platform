"""Session tokens + FastAPI access-context dependency.

HMAC-signed stateless tokens (prototype-grade, documented as such). The token
carries only the employee email; company and role are always re-resolved from
the registry server-side, so a tampered token cannot switch company or role.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

from nexus_platform.access_policy import RolePolicy, get_policy
from nexus_platform.registry import Company, Employee, get_registry

TOKEN_TTL_SECONDS = 12 * 3600
_SECRET = os.getenv("NEXUSIQ_PLATFORM_SECRET", "nexusiq-platform-demo-secret")


@dataclass(frozen=True)
class AccessContext:
    """Everything a request is allowed to touch. Built server-side only."""

    employee: Employee
    company: Company
    policy: RolePolicy

    @property
    def is_admin(self) -> bool:
        return self.employee.is_admin


def _sign(payload: str) -> str:
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(email: str) -> str:
    payload = json.dumps({"email": email.lower(), "exp": int(time.time()) + TOKEN_TTL_SECONDS})
    body = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{body}.{_sign(body)}"


def verify_token(token: str) -> str:
    """Return the employee email, or raise."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed session token")
    if not hmac.compare_digest(sig, _sign(body)):
        raise HTTPException(status_code=401, detail="Invalid session token")
    payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    return payload["email"]


def get_access_context(x_nexusiq_session: str = Header(default="")) -> AccessContext:
    """FastAPI dependency: resolve the session header into an AccessContext."""
    if not x_nexusiq_session:
        raise HTTPException(status_code=401, detail="Missing X-NexusIQ-Session header")
    email = verify_token(x_nexusiq_session)
    registry = get_registry()
    employee = registry.get_employee(email)
    if employee is None:
        raise HTTPException(status_code=401, detail="Unknown employee")
    company = registry.get_company(employee.company_slug)
    if company is None:
        raise HTTPException(status_code=401, detail="Employee has no company workspace")
    return AccessContext(employee=employee, company=company, policy=get_policy(employee.role))


def require_admin(ctx: AccessContext) -> None:
    if not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="This area is limited to Admin/CEO users of your company workspace.",
        )
