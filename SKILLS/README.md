# ServerSnap Skills Directory

This directory contains specialized operational and behavioral skills for developing, deploying, and maintaining ServerSnap.

---

## 🧭 Available Skills

| Skill | Folder | Purpose |
| :--- | :--- | :--- |
| **Passive_User** | [`Passive_User/`](file:///e:/Edelweiss_Projects/serversnap/SKILLS/Passive_User/SKILL.md) | Enforces non-invasive, strictly read-only monitoring on Linux servers. Guarantees that code never executes mutating writes as root to system configuration or OS targets. |
| **Feature_Preservation** | [`Feature_Preservation/`](file:///e:/Edelweiss_Projects/serversnap/SKILLS/Feature_Preservation/SKILL.md) | Enforces feature preservation rules, backward compatibility checks, and regression prevention protocols across all ServerSnap modules. |

---

## 🚀 How to Use These Skills

### In Antigravity / AI Pair Programming:
These skills are discovered automatically by Antigravity from `.agent/skills/` and `.agents/skills/`. They instruct the agent on how to:
- Audit and construct safe, non-destructive Linux collectors and probes.
- Safeguard host system integrity when running with elevated read privileges.
- Safely extend ServerSnap features without regressing existing capabilities.

### For Human Developers:
Refer to each skill's `SKILL.md` for coding patterns, subprocess safety standards, and operational guidelines before introducing new snapshot probes, API endpoints, or shell scripts.
