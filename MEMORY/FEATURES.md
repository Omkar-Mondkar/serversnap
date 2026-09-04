# ServerSnap — Complete Implemented Feature Catalog

This document details every feature currently implemented in ServerSnap. **All features listed below are active, tested, and must be preserved.**

---

## 1. Master Orchestrator (`bin/run_all.py`)

The central command-line entry point for running the agent snapshot lifecycle on any monitored Linux host.

### Features:
- **Sequential Pipeline Execution**:
  1. **Step 1 - Environment Validation**: Checks Python 3 environment, verifies config file existence, validates JSON syntax, extracts `server_id` and `report_dir`.
  2. **Step 1.5 - Central Platform Pre-flight Check**: Reaches out to `{central_url}/api/server/{server_id}/pending-config` with `X-API-Key`. Validates network connectivity, identifies authentication failures (HTTP 401), missing node registration (HTTP 404), or server unreachable errors prior to executing intensive snapshot tasks.
  3. **Step 2 - File & Metadata Snapshotting**: Invokes `bin/server_snapshot.py` with verbose logging. Handles exit code `0` (no drift) and `1` (drift detected) cleanly.
  4. **Step 3 - Network & Kernel Settings Collection**: Runs `bin/collect_network_snapshot.sh` to generate `Output/config-snapshot.yaml` unless `--no-network` is provided.
  5. **Step 4 - Unified Dashboard Generation**: Invokes `bin/visualize_report.py` to bake file drift, application binary inventory, and network snapshot data into an interactive single-file HTML report (`reports/dashboard/latest_dashboard_<server_id>.html`).
  6. **Step 4.5 - Central Platform Ingestion Push**: Reads latest snapshot and report, calculates cumulative baseline diff vs oldest snapshot, sanitizes configuration (stripping `api_key`, `secret_key`, `users`), base64-encodes the generated HTML dashboard, and POSTs the payload to `{platform.url}` with `X-API-Key`.
  7. **Step 5.5 - Baseline Comparison & Approval Check**: Integrates with `BaselineManager` and `ChangeApprover`. Checks for changes across 3 categories (`drift`, `app`, `network`). Automatically creates initial baselines if absent; records pending changes in `approvals/pending_<server_id>.json` if drift is detected.
  8. **Step 5 - Summary & Ready State Display**: Prints dashboard file locations, quick launch commands, and cron schedule recommendations.
  9. **Step 6 - Optional Local Web Server**: If `--serve` is supplied, launches `bin/serve_dashboard.py` on the configured or specified host/port.

### CLI Parameters:
- `--config <path>`: Path to `config.json` (default: `/else/serversnap/config/config.json`).
- `--app-dir <path>`: Directory scanned for application binaries (default: `/bin`).
- `--serve`: Starts the local HTTP dashboard server after generation.
- `--host <host>`: Bind host for HTTP server (overrides config).
- `--port <port>`: Port for HTTP server (default: 8080 or config).
- `--no-network`: Skips execution of `collect_network_snapshot.sh`.

---

## 2. File & Metadata Drift Engine (`bin/server_snapshot.py`)

Stateless, idempotent engine for tracking file and directory configuration drift.

### Features:
- **Zero-Dependency Architecture**: Pure Python standard library (`hashlib`, `difflib`, `fnmatch`, `glob`, `json`, `os`, `stat`, `urllib`).
- **Comprehensive Metadata Capture**:
  - SHA-256 content checksum.
  - File permissions in octal format (e.g. `0644`).
  - Owner UID and resolved username (POSIX via `pwd`, with fallback).
  - Group GID and resolved groupname (POSIX via `grp`, with fallback).
  - File size in bytes.
  - Modification timestamp (`mtime`) formatted in ISO 8601 UTC.
  - File type classification (`file`, `dir`, `symlink`, `socket`, `fifo`, `block`, `char`).
  - Symlink target resolution.
- **Granular Path Traversal Rules**:
  - Individual absolute file paths.
  - Recursive directory traversal (`recursive: true`).
  - Shallow/Non-recursive directory traversal (`recursive: false`).
  - Sub-tree exceptions and glob pattern overrides (e.g. `/etc/nginx/conf.d/*.conf`).
- **Smart Content Capture & Safety Limits**:
  - Configurable `include_content: true/false`.
  - Binary file detection (null-byte inspection) to prevent corrupting text diffs.
  - `max_content_size_bytes` guard (default: 5MB) preventing memory blowup or bloated snapshot JSON files.
- **Precise Drift Comparison**:
  - Compares previous JSON snapshot with current snapshot.
  - Classifies changes into `added`, `deleted`, `modified`.
  - Detailed modification breakdown: permission changes, ownership changes, size changes, mtime changes, and full unified diffs (`difflib.unified_diff`) for text files.
- **Atomic File Writing**:
  - Uses `tempfile.NamedTemporaryFile` + `os.replace` to ensure zero file corruption during power interruptions or concurrent reads.
  - Sets secure directory and file permissions (`0700` dirs, `0600` sensitive files).
- **Automated Retention & Pruning**:
  - Keeps the newest `retention_count` snapshots and reports per server.
  - Automatically cleans up older files after each execution.
- **Alerting Integration**:
  - **Local Command**: Executes local binary/script with environment variables (`SERVER_SNAPSHOT_SERVER_ID`, `SERVER_SNAPSHOT_ADDED`, `SERVER_SNAPSHOT_DELETED`, `SERVER_SNAPSHOT_MODIFIED`, `SERVER_SNAPSHOT_REPORT_JSON`, `SERVER_SNAPSHOT_REPORT_TEXT`).
  - **Webhook**: POSTs JSON alert summary to Slack, Discord, or custom webhook endpoints on drift.
- **Platform Ingest Push (`push_to_platform`)**:
  - Sends full snapshot, report diff, baseline diff, sanitized config, and Base64 dashboard to Central Platform.
  - Respects `push_always: true/false` flag.
  - Polls and processes Central pending configuration changes.

---

## 3. Central Fleet Management Hub (`bin/serve_central.py`)

Multi-server aggregation and web control plane.

### Features:
- **Stdlib HTTP Server**: Multi-threaded request handling using Python's `http.server` and `socketserver.ThreadingMixIn`.
- **Two-Layer Authentication**:
  1. **Agent-to-Central (API Key)**: Validates `X-API-Key` using constant-time string comparison (`hmac.compare_digest`).
  2. **Browser-to-Central (Session Cookie)**:
     - PBKDF2-HMAC-SHA256 password hashing with random salt.
     - HMAC-SHA256 signed session cookie (`sscentral_session`).
     - Session expiration timeout and cryptographic signature validation.
     - CLI utility: `python3 serve_central.py --hash-password <pwd>`.
- **Zero-Config Node Auto-Discovery**:
  - Automatically registers new agent nodes on their first push by creating `central_data/<server_id>/`.
  - Initializes metadata, baseline history, and storage directories without manual registration.
- **Hierarchical Configuration Cascade**:
  - Global defaults configured in `config/platform_config.json` (`stale_threshold_seconds`, `retention_count`, `cors_origins`).
  - Per-server overrides in `central_data/<server_id>/override.json` dynamically loaded per request.
- **Fleet Health State Engine**:
  - `healthy`: Recent snapshot received, zero drift detected.
  - `drift`: Recent snapshot received, unapproved changes detected.
  - `stale`: No snapshot received within `stale_threshold_seconds` (default: 3600s / 1 hour).
  - `critical`: High drift volume or prolonged offline state.
- **Central Storage & Archiving**:
  - `central_data/<server_id>/latest.json`: Latest full snapshot & change summary.
  - `central_data/<server_id>/latest_dashboard.html`: Latest rendered agent dashboard.
  - `central_data/<server_id>/history/`: Timestamped history archive with automated retention pruning.
  - `central_data/<server_id>/override.json`: Per-server custom settings.
  - `central_data/<server_id>/pending_config.json`: Queued configuration updates for remote agents.
- **RESTful Endpoints**:
  - `POST /api/ingest`: Agent snapshot + dashboard ingestion (X-API-Key protected).
  - `GET /api/servers`: Fleet health summary, status counts, server list (Session auth).
  - `GET /api/server/<server_id>`: Individual server snapshot, diffs, and metadata.
  - `GET /api/server/<server_id>/dashboard`: Direct proxy for the agent's interactive HTML report.
  - `GET /api/server/<server_id>/history`: Historical push records and timeline.
  - `GET /api/server/<server_id>/pending-config`: Agent polling for queued config updates.
  - `POST /api/server/<server_id>/pending-config`: Admin queuing of remote configuration updates.
  - `GET /api/server/<server_id>/override`: Fetch server-specific threshold overrides.
  - `POST /api/server/<server_id>/override`: Update server-specific threshold overrides.
  - `POST /api/server/<server_id>/approve`: Central baseline approval and auto-approval management.
  - `POST /api/login`, `POST /api/logout`, `GET /api/me`: Browser authentication lifecycle.

---

## 4. Central Fleet UI SPA (`bin/public/central.html`, `.js`, `.css`)

Single-page web application for monitoring and controlling the entire server fleet.

### Features:
- **Fleet Status Overview Bar**: Real-time counter cards showing Total Servers, Healthy Nodes, Drift Detected Nodes, and Stale/Offline Nodes.
- **Interactive Server Grid**:
  - Server cards displaying hostname, server ID, status badge, relative time ("5m ago", "2h ago"), added/deleted/modified change counters, and tags.
  - Click-to-inspect detail drawer / modal.
- **Search, Filter & Sort Controls**:
  - Text search by server ID and hostname.
  - Status filters: `All`, `Healthy`, `Drift`, `Stale`.
  - Sort by Last Seen, Server ID, or Drift Count.
- **Server Detail Inspection**:
  - Detailed change summary breakdown.
  - Side-by-side / inline diffs for modified configuration files.
  - Direct "Full Dashboard ↗" button opening the server's rendered report.
  - Pending Config manager allowing remote updates to agent monitoring paths.
  - Baseline approval controls directly from Central.
- **Auto-Refresh Engine**: Configurable polling intervals (10s, 30s, 60s, or Off) with pause-on-interaction.
- **Modern UI Styling**: Glassmorphic theme, responsive mobile-first grid, dark mode aesthetics, accessible contrasts.

---

## 5. Single-Node Visualizer & Report Generator (`bin/visualize_report.py`, `.html`, `.js`, `.css`)

Generates rich, standalone HTML dashboards representing a single server's complete state.

### Features:
- **Tab 1 — Configuration Drift**:
  - Overview cards: Files Added, Files Deleted, Files Modified.
  - Searchable file change list.
  - Rich unified diff viewer with syntax-highlighted additions (green) and deletions (red).
  - Metadata change inspector (permission mode, owner, group, file size, modification timestamp).
- **Tab 2 — Application Binary Snapshots**:
  - Binary inventory scanner for `/bin`, `/usr/bin`, `/opt`, or user-specified application directories.
  - Captures binary SHA-256 checksums, ELF architecture/type, permissions, and file size.
  - Detects newly added or altered binaries across runs.
- **Tab 3 — Network & System Settings**:
  - Visual tables for Sysctl kernel tuning parameters.
  - CPU power governor, C-States, and isolcpus parameters.
  - Network interface list with IP assignments, MAC addresses, and interface status.
  - Kernel routing table and default gateway status.
  - Active listening sockets and ports (`ss -tulpn`) with process IDs and program names.
  - Firewall rule inspector (`iptables` / `nftables`).
  - Core system binary checksums and integrity status.
- **Tab 4 — Baseline & Change Approval**:
  - Displays baseline comparison status for `drift`, `app`, and `network`.
  - Pending change review with one-click **Approve** and **Reject** buttons.
  - Interacts with `ApprovalAPIHandler` or local approval storage.

---

## 6. Golden Copy Baseline & Change Approval System

Maintains an authorized "Golden Copy" of server state and enforces approval workflows.

### Modules:
- **`BaselineManager` (`bin/baseline_manager.py`)**:
  - Manages approved golden baselines for 3 categories: `drift`, `app`, `network`.
  - Storage paths: `baselines/baseline_<server_id>_<category>.json` and history in `baselines/history_<server_id>_<category>.json`.
  - Auto-initializes approved baseline on the first run.
  - Compares incoming live snapshots with approved baseline to detect unapproved drift.
  - Atomic baseline updates upon user approval.
- **`ChangeApprover` (`bin/change_approver.py`)**:
  - Records pending changes into `approvals/pending_<server_id>.json`.
  - Manages approve / reject operations.
  - Maintains permanent approval logs in `approvals/approvals_<server_id>.json`.
- **`ApprovalAPIHandler` (`bin/approval_api.py`)**:
  - REST API interface connecting dashboard UI actions to baseline modifications.
- **`ReportApprovalStore` (`bin/report_approval_store.py`) & `AuditStore` (`bin/audit_store.py`)**:
  - Persistent storage and query engine for approval records and compliance audit trails.

---

## 7. Linux Network & Kernel Snapshot Collector (`bin/collect_network_snapshot.sh`)

Native Bash collector capturing 10 distinct categories of Linux server configuration into `Output/config-snapshot.yaml`:

1. **OS & Kernel Metadata**: Pretty OS name, kernel release version (`uname -r`).
2. **Sysctl & TCP Parameters**: Kernel scheduling parameters, network buffer limits (`rmem_max`, `wmem_max`), TCP window & keepalive tuning (`tcp_keepalive_time`, `tcp_tw_reuse`), virtual memory swappiness.
3. **CPU Power & Isolation**: `isolcpus`, `nohz_full`, CPU frequency scaling governor, disabled C-States count.
4. **Network Interfaces**: Interface names, IPv4/IPv6 addresses, subnet masks, MTU, operational status.
5. **Routing Tables**: Main routing table, default gateways, interface bindings.
6. **Active Listening Sockets**: Open TCP/UDP ports, bound addresses, socket states, owning process names and PIDs (`ss -tulpn`).
7. **Firewall Rules**: Active filter and NAT rules via `iptables-save` / `nft list ruleset`.
8. **System Binary Checksums**: SHA-256 hashes of critical administrative binaries (`/bin/login`, `/bin/sshd`, `/bin/sudo`, `/bin/su`, `/bin/bash`, `/bin/systemctl`).
9. **Recent Filesystem Modifications**: Files modified within the last 24–48 hours across `/etc`, `/usr/local/bin`, and `/var/log`.
10. **DNS & Resolver Settings**: Nameserver configuration from `/etc/resolv.conf` and static hosts from `/etc/hosts`.

---

## 8. Test Suites & Verification

- **`bin/test_serve_central.py`**: Validates Central server routing, API key ingestion, session cookie HMAC authentication, password hashing, config cascades, and endpoint security.
- **`bin/test_baseline_auto_approval.py`**: Validates Golden baseline lifecycle, change detection, approval recording, and auto-approval workflows.
- **`bin/test_agent_push.py`**: Validates agent push serialization, Base64 payload encoding, HTTP headers, error handling, and timeout behavior.
