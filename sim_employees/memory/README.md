# Simulation-employee memory

One JSON file per simulation employee: `<company>/<email>.json`. Each employee
remembers what it has asked the analyst and how the analyst answered, so day
to day it can re-probe weak spots and avoid repeating solved questions.

These files are written on disk (durable, inspectable) but **git-ignored** —
they change on every run, so committing them would create noise. The format:

```json
{
  "company": "acmecloud",
  "employee": "analyst@acmecloud.test",
  "role": "Analyst",
  "name": "Jordan Lee",
  "created": "2026-07-15T…",
  "interactions": [
    {
      "ts": "…", "question": "…", "family": "role-boundary-probe",
      "difficulty": "moderate", "route": "sql_agent",
      "access_decision": "allowed", "confidence": "N/A",
      "llm_used": false, "answer_summary": "…", "trace_id": "tr_…",
      "verdict": "answered"
    }
  ],
  "weak_spots": [
    {"topic": "…", "note": "re-probe differently", "evidence_trace": "tr_…", "ts": "…"}
  ],
  "notes": "free-text the CLI brain leaves for its future self"
}
```

See `../INSTRUCTIONS.md` for how the external CLI brain reads and updates this.
