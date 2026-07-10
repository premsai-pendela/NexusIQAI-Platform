"""Eval-gated repair helpers for the self-improving Health Check loop.

Hard structural rule: nothing in this package can merge anything. The only
exit is an open pull request that a human (Prem) reviews and merges. A grep
test (tests/platform_mode/test_repair_no_merge_path.py) fails the build if
any merge primitive appears in this package.
"""
