"""Live-mode HTTP client — drives the deployed analyst like a real browser.

In `live` mode a simulation employee logs in and posts questions to the
running API (default the AWS backend). The Fargate backend, which is inside
AWS and already talks to RDS, writes the trace — so simulated traffic lands in
the live database and shows on the Review page, with no direct DB access from
this machine and no firewall change. Uses only the standard library.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.nexusiq-ai.com/api/v1"


class LiveClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 90.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, body: dict, token: str = None) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("x-nexusiq-session", token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"{path} -> HTTP {e.code}: {detail}") from None

    def login(self, email: str, password: str) -> str:
        """Return a session token for this employee."""
        r = self._post("/platform/login", {"email": email, "password": password})
        token = r.get("token")
        if not token:
            raise RuntimeError(f"login returned no token for {email}")
        return token

    def query(self, token: str, question: str, session_id: str,
              source: str = "simulated") -> dict:
        """Ask one question. `source="simulated"` tags the server-written trace
        into the simulated bucket (never conflated with real). Returns the same
        shape the in-process runner reads: {"answer": str, "platform": {route,
        access_decision, confidence, llm_skipped, trace_id, ...}}."""
        r = self._post("/platform/query", {"question": question,
                                           "session_id": session_id,
                                           "source": source}, token)
        return {"answer": r.get("answer") or "", "platform": r.get("platform") or {}}
