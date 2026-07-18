"""AcmeCloud Analytics — company-scoped analyst overrides.

Company-specific fixes for AcmeCloud land HERE, not in the shared
orchestrator/deterministic code. Two hooks are recognized (both optional):

  EXTRA_METRIC_VOCABULARY: iterable[str]
      Extra words AcmeCloud's workspace recognizes as metric vocabulary.

  def find_clarification(question, features, policy):
      Company-scoped clarification rule, consulted before the shared rules.
      Return a Clarification, "pass" (explicitly fall through), or None.

Currently empty: no AcmeCloud-specific behavior has been needed yet — the
seam exists so the next company-specific fix has a collision-free home.
"""

EXTRA_METRIC_VOCABULARY: tuple = ()
