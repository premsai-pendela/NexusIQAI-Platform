"""Verification-governed learning loop.

Traces become failure records; failure records become repair proposals;
proposals are eval-gated and require human approval before adoption.
Nothing in this package mutates agent behavior on its own.
"""
