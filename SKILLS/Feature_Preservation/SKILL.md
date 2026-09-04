---
name: Feature_Preservation
description: >-
  Standard operating procedure for preserving all implemented ServerSnap features,
  preventing regressions, maintaining stdlib-only compatibility, and verifying contract integrity.
---

# Feature_Preservation Skill — Regression Prevention & Contract Integrity

This skill guides AI agents and developers on how to implement new capabilities in ServerSnap **without regressing, breaking, or altering any existing features**.

---

## 🧭 Preservation Principles

1. **Always Consult `MEMORY/FEATURES.md` First**:
   Before modifying any file (e.g. `run_all.py`, `server_snapshot.py`, `serve_central.py`, `visualize_report.py`), cross-reference the feature catalog to ensure all existing command flags, JSON keys, and endpoint responses remain intact.

2. **Additive-Only Evolution**:
   - Add new CLI options with sensible defaults; never remove or rename existing flags.
   - Add new JSON properties without mutating or removing existing schema fields.
   - Add new API endpoints without altering the contracts of existing endpoints.

3. **Strict Stdlib-Only Rule**:
   - Never import third-party pip libraries.
   - Rely solely on standard Python 3.8+ modules.

4. **Preserve Atomic File Protocol**:
   - All state updates on disk must use tempfile + atomic rename (`os.replace`) with restricted file modes (`0600`/`0700`).

---

## 🧪 Verification Protocol

Whenever a change is proposed or made:
1. Run existing test suites:
   ```bash
   python3 bin/test_serve_central.py
   python3 bin/test_baseline_auto_approval.py
   python3 bin/test_agent_push.py
   ```
2. Verify orchestrator end-to-end dry-run:
   ```bash
   python3 bin/run_all.py --help
   ```
3. Ensure no root writes or modifying commands were introduced.
