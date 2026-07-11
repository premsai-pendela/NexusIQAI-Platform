"""Simulation campaign runner.

Drives generated candidates through `query_service.run_query()` — the same
in-process entry point real requests use, inside the same 4-layer boundary —
with every trace tagged `source="simulated"`.

Budget discipline (hard rules, see ARCHITECTURE_LOG.md Guardrails):
- deliberate delay after every turn that actually took the LLM path;
- shared `utils/quota_tracker.py` — if the cloud providers are already in
  cooldown from real traffic, LLM-path candidates are skipped, not queued;
- hard per-campaign caps on LLM-path turns and estimated tokens; the
  campaign finishes its deterministic candidates and reports partial
  coverage instead of pushing past a cap.

The campaign never runs in any request hot path — CLI/manual trigger only
(scripts/run_sim_campaign.py).
"""

from __future__ import annotations

import os
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from nexus_platform import store
from nexus_platform.query_service import run_query
from nexus_platform.sim.classifier import Verdict, classify_turn, compute_oracle
from nexus_platform.sim.personas import persona_context
from nexus_platform.sim.question_gen import (Candidate, coverage_matrix,
                                             generate_candidates)

DELAY_SECONDS = float(os.getenv("SIMULATED_QUERY_DELAY_SECONDS", "8"))
MAX_LLM_CALLS = int(os.getenv("SIMULATED_MAX_LLM_CALLS", "40"))
MAX_EST_TOKENS = int(os.getenv("SIMULATED_MAX_TOKENS", "100000"))

# A single "analyze with AI"/planner question fans out to several internal
# provider calls; budget conservatively.
_EST_CALLS_PER_LLM_TURN = 3


def _providers_available() -> bool:
    try:
        from config.settings import settings
        from utils.quota_tracker import quota_tracker
        names = [getattr(settings, "gemini_flash_model", None),
                 getattr(settings, "groq_model", None)]
        return any(quota_tracker.is_available(n)[0] for n in names if n)
    except Exception:
        return True  # tracker unavailable → run_query's own fallback decides


def _needs_llm(candidate: Candidate) -> bool:
    if candidate.path_expected == "llm":
        return True
    return any(t.repeat_action == "analyze_with_ai" for t in candidate.turns)


def _lessons_for(company: str) -> list[dict]:
    lessons = store.list_active_lessons()
    return [l for l in lessons
            if l["scope"] in ("global", f"company:{company}")
            or l["scope"].startswith("deprioritize_family:")]


def _deprioritized_families(lessons: list[dict]) -> set[str]:
    return {l["scope"].split(":", 1)[1] for l in lessons
            if l["scope"].startswith("deprioritize_family:")}


def run_campaign(company: str, roles: Optional[list[str]] = None,
                 include_llm: bool = True,
                 max_llm_calls: int = MAX_LLM_CALLS,
                 max_est_tokens: int = MAX_EST_TOKENS,
                 delay_seconds: float = DELAY_SECONDS,
                 save_report: bool = True,
                 llm_roles: Optional[list[str]] = None) -> dict:
    campaign_id = f"camp_{uuid.uuid4().hex[:10]}"
    started = time.time()

    lessons = _lessons_for(company)
    depri = _deprioritized_families(lessons)
    candidates = generate_candidates(company, roles=roles,
                                     llm_roles=llm_roles)

    # Deprioritized families get half the seats, never zero — a wrong lesson
    # must stay falsifiable (over-generalization guardrail, Entry 2).
    if depri:
        kept, seen = [], Counter()
        for c in candidates:
            if c.family in depri:
                seen[c.family] += 1
                if seen[c.family] % 2 == 0:
                    continue
            kept.append(c)
        candidates = kept

    llm_turns_used = 0
    est_llm_calls = 0
    est_tokens = 0
    skipped: list[dict] = []
    rows: list[dict] = []
    findings_by_fp: dict[str, dict] = {}
    label_counts: Counter = Counter()
    errors: list[dict] = []

    for i, cand in enumerate(candidates):
        wants_llm = _needs_llm(cand)
        if wants_llm:
            if not include_llm:
                skipped.append({"family": cand.family, "role": cand.role,
                                "reason": "llm_disabled"})
                continue
            if (est_llm_calls + _EST_CALLS_PER_LLM_TURN > max_llm_calls
                    or est_tokens >= max_est_tokens):
                skipped.append({"family": cand.family, "role": cand.role,
                                "reason": "budget_cap"})
                continue
            if not _providers_available():
                skipped.append({"family": cand.family, "role": cand.role,
                                "reason": "provider_cooldown"})
                continue

        ctx = persona_context(company, cand.role)
        session_id = f"sim-{campaign_id}-{i}"
        cand_failed = False
        cand_llm_calls = 0
        try:
            for turn in cand.turns:
                oracle_nums = compute_oracle(ctx, turn.oracle_question)
                with store.tagged_trace_source("simulated"):
                    res = run_query(ctx, turn.question, session_id,
                                    repeat_action=turn.repeat_action)
                plat = res.get("platform") or {}
                trace_id = plat.get("trace_id") or ""
                answer = str(res.get("answer") or "")
                llm_used = not plat.get("llm_skipped", False)
                trace = store.get_trace(company, trace_id) if trace_id else None
                payload = (trace or {}).get("payload") or {}

                verdict: Verdict = classify_turn(
                    ctx, turn.expect, payload, trace_id, answer=answer,
                    oracle_nums=oracle_nums)
                label_counts[verdict.label] += 1
                surfaced = verdict.label in ("wrong", "exceptional")
                cand_failed = cand_failed or surfaced

                sim_id = store.save_sim_query(
                    company, campaign_id, cand.role, turn.question,
                    cand.generated_from, cand.family, cand.difficulty,
                    cand.path_expected, trace_id, session_id, llm_used,
                    tokens_estimated=(len(turn.question) + len(answer)) // 4)
                store.classify_sim_query(sim_id, verdict.label,
                                         verdict.confidence, verdict.reason,
                                         surfaced)
                rows.append({
                    "sim_id": sim_id, "family": cand.family,
                    "difficulty": cand.difficulty, "role": cand.role,
                    "question": turn.question, "expect": turn.expect,
                    "route": payload.get("route"), "label": verdict.label,
                    "reason": verdict.reason, "trace_id": trace_id,
                    "llm_used": llm_used,
                })

                for f in verdict.findings:
                    fp = f.get("fingerprint") or ""
                    if fp in findings_by_fp:
                        seen_f = findings_by_fp[fp]
                        seen_f["evidence"] = (seen_f["evidence"]
                                              + [e for e in f["evidence"]
                                                 if e not in seen_f["evidence"]])[:6]
                        seen_f["occurrences"] = seen_f.get("occurrences", 1) + 1
                    else:
                        findings_by_fp[fp] = {**f, "occurrences": 1}
                    store.upsert_finding(company, fp, f["classification"],
                                         f["severity"], f["summary"],
                                         payload={"kind": f["kind"],
                                                  "recommendation": f["recommendation"],
                                                  "evidence": f["evidence"],
                                                  "campaign_id": campaign_id})

                est_tokens += (len(turn.question) + len(answer)) // 4
                if llm_used:
                    llm_turns_used += 1
                    cand_llm_calls += _EST_CALLS_PER_LLM_TURN
                    est_llm_calls += _EST_CALLS_PER_LLM_TURN
                    time.sleep(delay_seconds)
        except Exception as exc:  # keep the campaign alive; log the wreck
            errors.append({"family": cand.family, "role": cand.role,
                           "error": f"{type(exc).__name__}: {exc}",
                           "trace": traceback.format_exc()[-800:]})
        store.bump_pattern_stats(company, cand.family, cand.difficulty,
                                 cand.role, campaign_id, ran=1,
                                 passed=0 if cand_failed else 1,
                                 failed=1 if cand_failed else 0,
                                 llm_calls=cand_llm_calls)

    findings = sorted(findings_by_fp.values(),
                      key=lambda f: ({"high": 0, "medium": 1, "low": 2,
                                      "info": 3}.get(f["severity"], 9),
                                     -f.get("occurrences", 1)))
    report = {
        "campaign_id": campaign_id,
        "company": company,
        "kind": "simulation_campaign",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - started, 1),
        "candidates_planned": len(candidates),
        "turns_run": len(rows),
        "labels": dict(label_counts),
        "coverage": coverage_matrix(candidates),
        "budget": {
            "llm_turns_used": llm_turns_used,
            "est_llm_calls": est_llm_calls,
            "max_llm_calls": max_llm_calls,
            "est_tokens": est_tokens,
            "max_est_tokens": max_est_tokens,
            "delay_seconds": delay_seconds,
            "skipped": skipped,
        },
        "lessons_applied": [l["lesson"][:120] for l in lessons],
        "findings": findings,
        "turns": rows,
        "errors": errors,
    }
    if save_report:
        report["report_id"] = store.save_health_report(
            company, f"health_check_agent:simulation:{campaign_id}", 0, report)

    surfaced_n = sum(1 for r in rows if r["label"] in ("wrong", "exceptional"))
    store.add_lesson(
        scope=f"company:{company}",
        lesson=(f"Campaign {campaign_id}: {len(rows)} turns, labels "
                f"{dict(label_counts)}, {surfaced_n} failure turn(s), "
                f"{len(findings)} distinct finding(s); LLM turns "
                f"{llm_turns_used}, est tokens {est_tokens}, skipped "
                f"{len(skipped)}. Top finding kinds: "
                f"{[f['kind'] for f in findings[:3]]}."),
        evidence=[campaign_id] + [r["trace_id"] for r in rows
                                  if r["label"] == "exceptional"][:4],
        campaign_id=campaign_id,
        expires_after=(datetime.now(timezone.utc)
                       + timedelta(days=30)).isoformat(),
    )
    return report
