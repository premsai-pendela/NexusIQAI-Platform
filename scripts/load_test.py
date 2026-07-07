"""Concurrency/load test — ~100 simultaneous employee questions.

Logs in a sample of the GENERATED employee population (not the curated demo
accounts) and fires concurrent Ask Analyst questions across deterministic,
refusal, clarification, and dashboard routes — all LLM-free by design, which
is exactly the production cost story: core analytics must survive without
any model provider.

Usage:
    python scripts/load_test.py [--base http://localhost:8000] [--n 100]

Writes reports/load_test_report.json and prints a summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_platform import store  # noqa: E402
from nexus_platform.scale.population import generated_password  # noqa: E402

QUESTION_MIX = [
    # (question, expected_route_prefixes)
    ("What was total revenue in Q3 2024?", ("deterministic", "repeat")),
    ("How many orders in Q2 2024?", ("deterministic", "repeat")),
    ("Revenue by region", ("deterministic", "repeat", "access_refusal")),
    ("Top 5 products by revenue", ("deterministic", "repeat", "access_refusal")),
    ("How many overdue invoices do we have?", ("deterministic", "repeat", "access_refusal")),
    ("Support tickets by priority", ("deterministic", "repeat", "access_refusal")),
    ("Headcount by department", ("deterministic", "repeat", "access_refusal")),
    ("What is our attrition rate?", ("deterministic", "repeat", "access_refusal")),
    ("revenue in q1 and q3", ("clarification",)),
    ("Give me a dashboard", ("dashboard",)),
]


async def one_question(client: httpx.AsyncClient, base: str, token: str,
                       email: str, i: int) -> dict:
    q, expected = QUESTION_MIX[i % len(QUESTION_MIX)]
    start = time.perf_counter()
    try:
        r = await client.post(
            f"{base}/api/v1/platform/query",
            headers={"X-NexusIQ-Session": token},
            json={"question": q, "session_id": f"load-{email[:20]}-{i}"},
            timeout=60.0,
        )
        elapsed = time.perf_counter() - start
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "latency": elapsed,
                    "question": q}
        body = r.json()
        route = str((body.get("platform") or {}).get("route") or "")
        route_ok = any(route.startswith(p) for p in expected)
        llm_used = (body.get("platform") or {}).get("llm_skipped") is False
        return {"ok": True, "status": 200, "latency": elapsed, "question": q,
                "route": route, "route_ok": route_ok, "llm_used": llm_used}
    except Exception as exc:
        return {"ok": False, "status": None, "latency": time.perf_counter() - start,
                "question": q, "error": str(exc)[:120]}


async def run(base: str, n: int) -> dict:
    # Sample generated employees across all three companies.
    logins = []
    for slug in ("acmecloud", "medcore", "finpilot"):
        for row in store.list_generated_employees(slug, limit=40):
            m = re.search(r"(\d+)@", row["email"])
            if m:
                logins.append((slug, row["email"],
                               generated_password(slug, int(m.group(1)))))
    random.Random(7).shuffle(logins)
    logins = logins[:n]
    if len(logins) < n:
        raise RuntimeError(f"only {len(logins)} generated employees available; "
                           "run scale.population first")

    async with httpx.AsyncClient() as client:
        # Phase 1: concurrent logins
        t0 = time.perf_counter()
        login_results = await asyncio.gather(*[
            client.post(f"{base}/api/v1/platform/login",
                        json={"email": email, "password": pw}, timeout=30.0)
            for _, email, pw in logins])
        login_time = time.perf_counter() - t0
        tokens = []
        for (slug, email, _), resp in zip(logins, login_results):
            if resp.status_code == 200:
                tokens.append((email, resp.json()["token"]))
        if len(tokens) < n * 0.95:
            raise RuntimeError(f"logins failed: {len(tokens)}/{n} succeeded")

        # Phase 2: n simultaneous questions
        t0 = time.perf_counter()
        results = await asyncio.gather(*[
            one_question(client, base, token, email, i)
            for i, (email, token) in enumerate(tokens)])
        wall = time.perf_counter() - t0

    oks = [r for r in results if r["ok"]]
    lats = sorted(r["latency"] for r in oks)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "concurrent_questions": len(results),
        "distinct_employees": len(tokens),
        "login_phase_s": round(login_time, 2),
        "wall_clock_s": round(wall, 2),
        "success": len(oks),
        "failed": len(results) - len(oks),
        "success_rate": round(len(oks) / len(results), 4),
        "route_correct": sum(1 for r in oks if r.get("route_ok")),
        "llm_calls_used": sum(1 for r in oks if r.get("llm_used")),
        "latency_p50_s": round(statistics.median(lats), 3) if lats else None,
        "latency_p95_s": round(lats[int(len(lats) * 0.95) - 1], 3) if lats else None,
        "latency_max_s": round(max(lats), 3) if lats else None,
        "throughput_qps": round(len(oks) / wall, 1) if wall else None,
        "routes": {},
        "failures": [r for r in results if not r["ok"]][:10],
    }
    for r in oks:
        report["routes"][r["route"]] = report["routes"].get(r["route"], 0) + 1
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    report = asyncio.run(run(args.base, args.n))
    out_dir = Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "load_test_report.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"\n=== NexusIQAI load test — {report['concurrent_questions']} "
          f"simultaneous employee questions ===")
    print(f"success: {report['success']}/{report['concurrent_questions']} "
          f"({report['success_rate']:.1%})  wall: {report['wall_clock_s']}s  "
          f"throughput: {report['throughput_qps']} q/s")
    print(f"latency p50 {report['latency_p50_s']}s · p95 {report['latency_p95_s']}s "
          f"· max {report['latency_max_s']}s")
    print(f"routes: {report['routes']}")
    print(f"LLM calls used: {report['llm_calls_used']} (deterministic-first by design)")
    print(f"report: {out}")
    if report["success_rate"] < 0.98:
        sys.exit(1)


if __name__ == "__main__":
    main()
