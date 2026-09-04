# ServerSnap — AI Agent Operational & Architectural Rules

All AI agents assisting with this codebase must strictly adhere to the following rules:

---

## 1. 🛡️ Mandatory Feature Preservation
- Before modifying or adding any code, inspect the `MEMORY/` directory:
  - [`MEMORY/README.md`](file:///e:/Edelweiss_Projects/serversnap/MEMORY/README.md)
  - [`MEMORY/FEATURES.md`](file:///e:/Edelweiss_Projects/serversnap/MEMORY/FEATURES.md)
  - [`MEMORY/ARCHITECTURE.md`](file:///e:/Edelweiss_Projects/serversnap/MEMORY/ARCHITECTURE.md)
  - [`MEMORY/CONFIG_AND_STORAGE_SPEC.md`](file:///e:/Edelweiss_Projects/serversnap/MEMORY/CONFIG_AND_STORAGE_SPEC.md)
  - [`MEMORY/INVARIANTS.md`](file:///e:/Edelweiss_Projects/serversnap/MEMORY/INVARIANTS.md)
- **PRESERVE ALL EXISTING FEATURES AT ALL COSTS.** No change may break, alter, or remove existing CLI flags, configuration parameters, API routes, or data formats.

---

## 2. 🔒 Passive User / Zero Root Write Rule (`Passive_User`)
- ServerSnap is a strictly passive, read-only configuration tracking and drift monitoring tool.
- **NO CODE MUST EVER WRITE AS ROOT TO HOST SYSTEM CONFIGURATION OR OS TARGETS.**
- Root access (if used) is strictly **READ-ONLY** (reading `/etc`, reading sysctl, reading `iptables-save`, querying `ss -tulpn`).
- All file writes performed by the application must be strictly restricted to the application's own local data directories (`snapshots/`, `reports/`, `baselines/`, `approvals/`, `central_data/`, `Output/`, `logs/`).
- Refer to [`SKILLS/Passive_User/SKILL.md`](file:///e:/Edelweiss_Projects/serversnap/SKILLS/Passive_User/SKILL.md) for detailed guidelines.

---

## 3. 📦 Pure Standard Library Requirement
- Zero external pip dependencies.
- All Python code must rely strictly on standard library modules (`http.server`, `urllib.request`, `hashlib`, `hmac`, `json`, `difflib`, `subprocess`, `stat`, `dataclasses`, etc.).
- Shell scripts must use standard POSIX / Linux native utilities.

---

## 4. 💾 Atomic Disk Writes
- Never overwrite active data files in-place.
- Always use `tempfile.NamedTemporaryFile` + `os.replace` with strict permissions (`0600` for files, `0700` for directories).
