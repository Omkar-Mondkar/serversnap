# ServerSnap — System Invariants & Preservation Rules

This document outlines the **non-negotiable rules and invariant contracts** of ServerSnap. Any modification, feature addition, or refactoring must strictly adhere to these rules.

---

## 🛑 1. Core Invariants (MUST NEVER BE BROKEN)

### Invariant 1: Zero Root Writes to Monitored Linux Targets (`Passive_User` Rule)
- ServerSnap is an observer, not a mutating agent.
- **NO PART OF SERVERSNAP MAY EVER WRITE TO OR MUTATE SYSTEM CONFIGURATION ON MONITORED LINUX SERVERS.**
- The application may only write to its own designated output and storage directories (`snapshots/`, `reports/`, `baselines/`, `approvals/`, `central_data/`, `logs/`, `Output/`).
- System probes, network commands, and file readers must be strictly read-only (`cat`, `stat`, `ss`, `ip`, `sysctl -n`, `iptables -S`).

### Invariant 2: Pure Python Standard Library (Stdlib Only)
- ServerSnap agent and central components **MUST NOT** require external pip packages (no `requests`, `flask`, `fastapi`, `pydantic`, `sqlalchemy`, etc.).
- Everything must rely strictly on standard library modules (`urllib.request`, `http.server`, `hashlib`, `hmac`, `json`, `difflib`, `subprocess`, `stat`, `dataclasses`, etc.).
- This ensures ServerSnap can be deployed instantly on bare-metal servers, minimal containers, and enterprise Linux distributions (RHEL, Ubuntu, Debian, Rocky Linux) without installing compilers or package managers.

### Invariant 3: Stateless & Idempotent Agent Snapshotting
- The agent holds no in-memory state across runs.
- Running the snapshot tool multiple times consecutively on an unchanged filesystem must produce identical metadata and zero detected drift.
- All historical comparisons must be derived strictly from verified JSON snapshot files on disk.

### Invariant 4: Atomic Disk I/O Protocol
- Never overwrite existing active data files in-place.
- Always write to a temporary file (`tempfile.NamedTemporaryFile` in the same directory), flush and fsync, then perform an atomic rename (`os.replace`).
- This protects data integrity against sudden power loss, kernel panics, or concurrent HTTP read requests.

### Invariant 5: Constant-Time & Safe Authentication
- Never use direct string equality (`==`) to check secret tokens or API keys.
- Always use `hmac.compare_digest` to prevent timing attacks.
- Browser session passwords must use PBKDF2-HMAC-SHA256 with cryptographically secure random salts.
- Session cookies must be signed using HMAC-SHA256 with a strong secret key.

### Invariant 6: Graceful Degradation
- If optional modules (`collect_network_snapshot.sh`, `baseline_manager.py`) are missing or unprivileged, the pipeline must log an informative message and continue rather than crashing.
- If network collection fails due to lack of `iptables` permissions in an unprivileged user context, the drift dashboard must still be generated cleanly with file drift.

---

## 🛡️ 2. Regression Prevention & Preservation Checklist

Before finalizing any changes to ServerSnap, the AI agent must verify the following checklist:

| Category | Verification Item | Status Check |
| :--- | :--- | :--- |
| **CLI Compatibility** | All existing CLI flags (`--config`, `--app-dir`, `--serve`, `--host`, `--port`, `--no-network`, `-v`, `--no-alert`) remain functional with exact names and defaults. | Mandatory |
| **Data Schema** | Snapshot JSON, report JSON, and platform ingest payload schemas remain backward-compatible with existing parsers. | Mandatory |
| **Central Platform** | Ingestion endpoint `POST /api/ingest` handles existing agent payloads without breaking. Web UI continues rendering server cards and diff views. | Mandatory |
| **Golden Baseline** | Baselines for `drift`, `app`, and `network` continue to support auto-initialization, diff detection, and manual approval. | Mandatory |
| **Security Boundaries** | Zero root writes to system targets; secure file permissions (`0700` dirs, `0600` configs); no API keys leaked in HTML/payload logs. | Mandatory |
| **Standard Library** | No third-party pip dependencies introduced into runtime code. | Mandatory |
