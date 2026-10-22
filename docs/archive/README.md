# Archived reports (pre-October-2026 audit)

These documents describe TruthLens **before** the October 2026 audit and rework. They are kept for history only.

Several statements in them did not hold when tested, for example:
- "All end-to-end tests passed" / "100% pass rate": the regression test imported a deleted module, and the
  benchmark scored 2/10 (20%).
- The verdict pipeline described here discarded correct REFUTED verdicts and contained hard-coded demo answers.
- "Zero-shot NLI DeBERTa" was advertised but never called.
- The source dossiers cited invented report IDs.

For the current design, see `../VERIFICATION_ENGINE.md`, `../EVIDENCE_POLICY.md` and the top-level `README.md`.
