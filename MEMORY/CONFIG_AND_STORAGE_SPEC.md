# ServerSnap — Configuration Schemas & Storage Specification

This document defines the exact schemas, configuration cascades, filesystem storage layouts, and atomic writing protocols used across ServerSnap.

---

## 1. Directory & Storage Layout

### 1.1 Agent Node Filesystem Layout
```
/else/serversnap/ (or workspace root)
├── bin/
│   ├── run_all.py                   # Master orchestrator
│   ├── server_snapshot.py           # Core file drift snapshot tool
│   ├── collect_network_snapshot.sh  # Linux network/kernel collector
│   ├── visualize_report.py          # HTML dashboard generator
│   ├── baseline_manager.py          # Golden copy baseline manager
│   ├── change_approver.py           # Change approval engine
│   ├── approval_api.py              # REST API handler for approvals
│   ├── serve_dashboard.py           # Standalone local HTTP server
│   └── public/                      # Static assets for dashboards
│       ├── visualize_report.html
│       ├── visualize_report.js
│       ├── visualize_report.css
│       ├── central.html
│       ├── central.js
│       └── central.css
├── config/
│   ├── config.json                  # Active agent configuration
│   └── config.json.sample           # Sample template
├── snapshots/                       # Generated snapshot archives (mode 0700)
│   └── snapshot_<server_id>_<timestamp>.json
├── reports/                         # Generated drift reports (mode 0700)
│   ├── report_<server_id>_<timestamp>.json
│   ├── report_<server_id>_<timestamp>.txt
│   └── dashboard/
│       └── latest_dashboard_<server_id>.html
├── baselines/                       # Golden copy approved baselines
│   ├── baseline_<server_id>_drift.json
│   ├── baseline_<server_id>_app.json
│   ├── baseline_<server_id>_network.json
│   ├── history_<server_id>_drift.json
│   ├── history_<server_id>_app.json
│   └── history_<server_id>_network.json
├── approvals/                       # Pending & historical approvals
│   ├── pending_<server_id>.json
│   └── approvals_<server_id>.json
├── Output/                          # Network snapshot output
│   └── config-snapshot.yaml
└── logs/                            # Rotating execution logs
    └── server_snapshot.log
```

### 1.2 Central Hub Filesystem Layout
```
/else/serversnap/ (or central server root)
├── bin/
│   ├── serve_central.py             # Central HTTP hub daemon
│   └── public/                      # Central UI assets
│       ├── central.html
│       ├── central.js
│       └── central.css
├── config/
│   ├── platform_config.json         # Active central platform configuration
│   └── platform_config.json.sample  # Sample template
└── central_data/                    # Node data repository
    └── <server_id>/                 # Per-node data directory (auto-created)
        ├── latest.json              # Latest ingested snapshot, diff & metadata
        ├── latest_dashboard.html    # Full agent-rendered SPA dashboard
        ├── override.json            # Node-specific overrides (stale threshold, retention)
        ├── pending_config.json      # Queued configuration updates waiting for agent pull
        └── history/                 # Timestamped ingestion archives
            └── snapshot_<timestamp>.json
```

---

## 2. Configuration Schemas

### 2.1 Agent Configuration (`config/config.json`)

```json
{
  "server_id": "web01",
  "hostname": "web01.example.internal",
  "snapshot_dir": "/else/serversnap/snapshots",
  "report_dir": "/else/serversnap/reports",
  "log_file": "/else/serversnap/logs/server_snapshot.log",
  "max_content_size_bytes": 5242880,
  "retention_count": 30,
  "paths": [
    {
      "path": "/etc/sysctl.conf",
      "include_content": true
    },
    {
      "path": "/etc/nginx",
      "recursive": true,
      "include_content": false,
      "exceptions": [
        {
          "path": "/etc/nginx/nginx.conf",
          "include_content": true
        },
        {
          "pattern": "/etc/nginx/conf.d/*.conf",
          "include_content": true
        }
      ]
    }
  ],
  "alerting": {
    "command": null,
    "webhook_url": null
  },
  "dashboard": {
    "host": "127.0.0.1",
    "port": 8080
  },
  "platform": {
    "url": "http://10.0.0.50:8090/api/ingest",
    "api_key": "YOUR_CENTRAL_API_KEY_HERE",
    "push_always": true
  }
}
```

### 2.2 Central Platform Configuration (`config/platform_config.json`)

```json
{
  "bind_host": "0.0.0.0",
  "bind_port": 8090,
  "api_key": "CENTRAL_SECRET_API_KEY",
  "secret_key": "RANDOM_HMAC_SECRET_FOR_SESSIONS",
  "data_dir": "central_data",
  "session_timeout_seconds": 86400,
  "stale_threshold_seconds": 3600,
  "retention_count": 50,
  "users": {
    "admin": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855:5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
  }
}
```

### 2.3 Server Override Configuration (`central_data/<server_id>/override.json`)

```json
{
  "stale_threshold_seconds": 7200,
  "retention_count": 100,
  "tags": ["production", "database"],
  "notes": "Primary database server; longer stale threshold permitted."
}
```

---

## 3. Configuration Cascade Rules

When computing server status or retention policies, ServerSnap applies the following precedence:

```
+-------------------------------------------------------------+
| 1. Per-Server Override File                                 |
|    (central_data/<server_id>/override.json)                 |
|    [Highest Priority - Loaded dynamically on each request]  |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
| 2. Central Platform Configuration Defaults                  |
|    (config/platform_config.json)                            |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
| 3. Built-in Code Hardcoded Fallbacks                        |
|    (e.g., stale_threshold = 3600s, retention_count = 30)    |
|    [Lowest Priority]                                        |
+-------------------------------------------------------------+
```

---

## 4. Atomic File Write Protocol

To prevent corrupted files during sudden server restarts, network disconnections, or concurrent read requests, all persistent file writes (snapshots, reports, baselines, central data) **MUST** follow this atomic sequence:

```python
import os
import tempfile
import json

def atomic_write_json(target_path: str, data: dict, mode: int = 0o600) -> None:
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    
    # 1. Create named temporary file in the same directory/filesystem
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target_dir, delete=False) as tf:
        temp_name = tf.name
        json.dump(data, tf, indent=2, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())  # Ensure bytes hit disk
    
    # 2. Set strict file permissions
    os.chmod(temp_name, mode)
    
    # 3. Atomic replace
    os.replace(temp_name, target_path)
```
