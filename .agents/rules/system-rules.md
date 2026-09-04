---
description: Permanent system rules for ServerSnap - Feature Preservation and Passive User Read-Only Mandate
trigger: always_on
---

# ServerSnap Agent System Rules

1. **Feature Preservation**: Always consult `MEMORY/FEATURES.md` and `MEMORY/INVARIANTS.md` before making code edits. Never remove, regress, or alter existing CLI options, APIs, or schemas.
2. **Passive User Policy**: ServerSnap is a passive configuration tracking tool. Never execute write operations as root to any host OS targets or configs. All root operations are strictly read-only.
3. **Pure Stdlib**: Do not introduce third-party pip dependencies.
4. **Atomic Writes**: Always write application data files using tempfiles + `os.replace`.
