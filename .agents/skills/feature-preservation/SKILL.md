---
name: feature-preservation
description: >-
  Enforces preservation of all implemented ServerSnap features,
  preventing regressions, maintaining stdlib-only compatibility, and verifying contract integrity.
---

# Feature Preservation Skill

## 🎯 Directive
When modifying or extending ServerSnap:
- Read and verify `MEMORY/FEATURES.md` and `MEMORY/INVARIANTS.md`.
- Preserve all existing CLI arguments, JSON schemas, API endpoints, and UI capabilities.
- Maintain pure Python 3 standard library compatibility (zero pip dependencies).
- Ensure atomic disk writes with secure file modes (`0600`/`0700`).
