#!/usr/bin/env python3
"""
visualize_report.py
====================


Generates a modern, self-contained, fully offline HTML dashboard from one or
more server_snapshot.py JSON change reports, so drift can be reviewed visually
instead of by reading raw JSON/text.


Design goals (matching server_snapshot.py):
  - Stdlib only, no external dependencies, no CDN/network calls. All CSS/JS is
    embedded inline in the generated HTML, so the file can be viewed directly
    on the server, or copied/scp'd to a laptop and opened in any browser with
    zero setup.
  - Read-only / side-effect-free with respect to snapshots and reports: this
    script never deletes, modifies, or re-generates report data. It only
    reads existing report_*.json files and writes a new .html file.
  - Works standalone. You can point it at a single report file, or let it
    pull the report directory + server_id straight out of config.json, or a
    server_id you pass on the command line. If none is given, it also runs
    fine against a --report-dir with no config.json present at all (e.g. a
    reports/ directory copied off a server onto your laptop).


Usage:
  # Use config.json to find report_dir/server_id, dashboard covers all
  # available reports in the directory:
  visualize_report.py --config /else/server_snapshot/config/config.json


  # Bundle the N most recent reports for this server (0 = all available):
  visualize_report.py --config /else/server_snapshot/config/config.json --history 20


  # Visualize one specific report file directly (no config.json needed):
  visualize_report.py --report /else/server_snapshot/reports/report_web01_2026_07_29_09_54_16.json


  # Point directly at a reports directory + server_id (no config.json needed):
  visualize_report.py --report-dir ./reports --server-id web01


  # Custom output path (default: report_dir/dashboard/):
  visualize_report.py --config ... --output /tmp/dashboard.html


Each run writes a timestamped file (dashboard_<server_id>_<ts>.html) plus
updates a stable-name copy (latest_dashboard_<server_id>.html) in the same
directory, so a URL pointing at the stable name always reflects the most
recent run without changing. By default that directory is a dedicated
report_dir/dashboard/ subfolder (not report_dir itself) so an HTTP server can
be pointed only at rendered dashboards, never at raw report/snapshot JSON.
See bin/serve_dashboard.py to publish that folder over HTTP.


Exit codes:
  0 - dashboard generated successfully
  2 - fatal error (bad arguments, no reports found, could not read/write files)
"""


from __future__ import annotations


import argparse
import glob
import html
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG_PATH = "/else/server_snapshot/config/config.json"
SCRIPT_VERSION = "1.1.0"




class VisualizeError(Exception):
    """Raised for any fatal problem building the dashboard."""


# ---------------------------------------------------------------------------
# Config / report discovery
# ---------------------------------------------------------------------------


def load_minimal_config(config_path: str) -> Dict[str, Any]:
    if not os.path.isfile(config_path):
        raise VisualizeError(f"Config file not found: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"Failed to read/parse config file {config_path}: {exc}") from exc


    missing = [k for k in ("server_id", "report_dir") if k not in raw]
    if missing:
        raise VisualizeError(f"Config is missing required key(s) for this tool: {', '.join(missing)}")
    return raw




def gather_report_paths(report_dir: str, server_id: str, history: int) -> List[str]:
    """Return the `history` most recent report_<server_id>_*.json files
    (oldest first). Filenames use a YYYY_MM_DD_HH_MM_SS timestamp so lexical
    sort == chronological sort. Deliberately excludes latest_report_*.json
    and compare_*.json (different prefixes) to avoid double-counting.
    If history == 0, returns ALL matching report files."""
    pattern = os.path.join(report_dir, f"report_{server_id}_*.json")
    files = sorted(glob.glob(pattern))
    if history > 0:
        files = files[-history:]
    return files




def load_report_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"Failed to read/parse report file {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
__CSS__
</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-left">
      <div class="logo">&#9635;</div>
      <div class="titles">
        <h1>Server Snapshot Dashboard</h1>
        <p id="subtitle" class="subtitle">&mdash;</p>
      </div>
    </div>
    <div class="topbar-right">
      <div class="field multi-select-field">
        <label>Reports</label>
        <div class="multi-select" id="reportMultiSelect">
          <div class="multi-select-trigger" id="reportTrigger" tabindex="0">
            <span id="reportSelectedText">Select reports&hellip;</span>
            <span class="ms-chevron">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="reportDropdown">
            <div class="ms-actions">
              <button type="button" id="selectAll" class="ms-btn">Select All</button>
              <button type="button" id="deselectAll" class="ms-btn">Deselect All</button>
            </div>
            <div id="reportCheckboxes" class="ms-options"></div>
          </div>
        </div>
      </div>
      <div class="field search-field">
        <label for="searchBox">Filter path</label>
        <input id="searchBox" type="text" placeholder="e.g. nginx.conf, /etc, sshd..." autocomplete="off">
      </div>
      <button id="themeToggle" class="icon-btn" title="Toggle light/dark theme">&#9788;</button>
    </div>
  </header>

  <nav class="tab-bar">
    <button class="tab active" data-tab="reports" id="tabReports">&#128202; Reports</button>
    <button class="tab" data-tab="config" id="tabConfig">&#9881; Configuration</button>
  </nav>

  <main>
    <div id="reportsView">
      <section class="meta-bar">
        <div class="meta-item"><span class="meta-label">Server ID</span><span id="metaServerId" class="meta-value">&mdash;</span></div>
        <div class="meta-item"><span class="meta-label">Hostname</span><span id="metaHostname" class="meta-value">&mdash;</span></div>
        <div class="meta-item"><span class="meta-label">Generated</span><span id="metaGenerated" class="meta-value">&mdash;</span></div>
        <div class="meta-item"><span class="meta-label">Previous snapshot</span><span id="metaPrev" class="meta-value mono">&mdash;</span></div>
        <div class="meta-item"><span class="meta-label">Current snapshot</span><span id="metaCurr" class="meta-value mono">&mdash;</span></div>
      </section>

      <section class="cards">
        <div class="card card-added">
          <div class="card-icon">+</div>
          <div class="card-body"><div id="countAdded" class="card-count">0</div><div class="card-label">Added</div></div>
        </div>
        <div class="card card-deleted">
          <div class="card-icon">&minus;</div>
          <div class="card-body"><div id="countDeleted" class="card-count">0</div><div class="card-label">Deleted</div></div>
        </div>
        <div class="card card-modified">
          <div class="card-icon">&#9998;</div>
          <div class="card-body"><div id="countModified" class="card-count">0</div><div class="card-label">Modified</div></div>
        </div>
        <div class="card card-unchanged">
          <div class="card-icon">&#10003;</div>
          <div class="card-body"><div id="countUnchanged" class="card-count">0</div><div class="card-label">Unchanged</div></div>
        </div>
      </section>

      <section class="bar-wrap">
        <div id="statusBar" class="status-bar">
          <div class="status-seg seg-added" style="width:0%"></div>
          <div class="status-seg seg-deleted" style="width:0%"></div>
          <div class="status-seg seg-modified" style="width:0%"></div>
          <div class="status-seg seg-unchanged" style="width:0%"></div>
        </div>
      </section>

      <section id="emptyState" class="empty-state" style="display:none">
        <div class="empty-icon">&#10003;</div>
        <p>No differences detected between the previous and current snapshot.</p>
      </section>

      <section id="addedSection" class="panel">
        <h2 class="panel-title added-title">Added <span id="addedTitleCount" class="panel-count"></span></h2>
        <ul id="addedList" class="path-list"></ul>
      </section>

      <section id="deletedSection" class="panel">
        <h2 class="panel-title deleted-title">Deleted <span id="deletedTitleCount" class="panel-count"></span></h2>
        <ul id="deletedList" class="path-list"></ul>
      </section>

      <section id="modifiedSection" class="panel">
        <h2 class="panel-title modified-title">Modified <span id="modifiedTitleCount" class="panel-count"></span></h2>
        <div id="modifiedList" class="modified-list"></div>
      </section>
    </div>

    <div id="configView" style="display:none">
      <div id="configUnavailable" class="empty-state">
        <div class="empty-icon">&#9881;</div>
        <p>Configuration management requires the dashboard server (server_dashboard.py).<br>
        Open this dashboard via the server to enable config editing.</p>
      </div>

      <div id="configContent" style="display:none">
        <section class="panel config-section">
          <h2 class="panel-title config-title">General Settings</h2>
          <div class="config-form" id="generalForm">
            <div class="form-group"><label for="cfgServerId">Server ID *</label><input type="text" id="cfgServerId"></div>
            <div class="form-group"><label for="cfgHostname">Hostname</label><input type="text" id="cfgHostname" placeholder="auto-detect if empty"></div>
            <div class="form-group"><label for="cfgSnapshotDir">Snapshot Directory *</label><input type="text" id="cfgSnapshotDir"></div>
            <div class="form-group"><label for="cfgReportDir">Report Directory *</label><input type="text" id="cfgReportDir"></div>
            <div class="form-group"><label for="cfgLogFile">Log File</label><input type="text" id="cfgLogFile" placeholder="optional"></div>
            <div class="form-group"><label for="cfgMaxContentSize">Max Content Size (bytes)</label><input type="number" id="cfgMaxContentSize" value="5242880"></div>
            <div class="form-group"><label for="cfgRetentionCount">Retention Count</label><input type="number" id="cfgRetentionCount" value="30"></div>
          </div>
        </section>

        <section class="panel config-section">
          <h2 class="panel-title config-title">Monitored Paths <button type="button" id="addPathBtn" class="btn btn-sm btn-accent">+ Add Path</button></h2>
          <div id="pathsList" class="paths-list"></div>
          <div id="pathsEmpty" class="paths-empty">No monitored paths configured.</div>
        </section>

        <section class="panel config-section">
          <h2 class="panel-title config-title">Alerting</h2>
          <div class="config-form">
            <div class="form-group"><label for="cfgAlertCommand">Alert Command</label><input type="text" id="cfgAlertCommand" placeholder="null (disabled)"></div>
            <div class="form-group"><label for="cfgWebhookUrl">Webhook URL</label><input type="text" id="cfgWebhookUrl" placeholder="null (disabled)"></div>
          </div>
        </section>

        <section class="panel config-section">
          <h2 class="panel-title config-title">Dashboard Settings</h2>
          <div class="config-form">
            <div class="form-group"><label for="cfgDashHost">Host</label><input type="text" id="cfgDashHost" value="127.0.0.1"></div>
            <div class="form-group"><label for="cfgDashPort">Port</label><input type="number" id="cfgDashPort" value="8080"></div>
          </div>
        </section>

        <div class="config-actions">
          <button type="button" id="reloadConfigBtn" class="btn btn-secondary">&#8635; Reload</button>
          <button type="button" id="saveConfigBtn" class="btn btn-primary">&#128190; Save Configuration</button>
        </div>
      </div>
    </div>
  </main>

  <div id="pathModal" class="modal-overlay" style="display:none">
    <div class="modal">
      <div class="modal-header">
        <h3 id="pathModalTitle">Add Monitored Path</h3>
        <button type="button" class="modal-close" id="pathModalClose">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group"><label for="modalPath">Path (absolute) *</label><input type="text" id="modalPath" placeholder="/etc/nginx"></div>
        <div class="form-row">
          <label class="toggle-label"><input type="checkbox" id="modalRecursive" checked> Recursive</label>
          <label class="toggle-label"><input type="checkbox" id="modalIncludeContent"> Include Content</label>
        </div>
        <div class="form-group">
          <div class="exc-header"><label>Exceptions</label><button type="button" class="btn btn-xs btn-secondary" id="addExceptionBtn">+ Add</button></div>
          <div id="modalExceptions" class="exceptions-list"></div>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" id="pathModalCancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="pathModalSave">Save</button>
      </div>
    </div>
  </div>

  <div id="toastContainer" class="toast-container"></div>

  <footer class="footer">
    Generated by visualize_report.py __SCRIPT_VERSION__ &middot; fully offline, no external dependencies &middot; rendered __RENDERED_AT__
  </footer>

<script id="report-data" type="application/json">__REPORT_DATA_JSON__</script>
<script>
__JS__
</script>
</body>
</html>
"""


CSS = """
:root {
  --bg: #0b0f19;
  --bg-alt: #121826;
  --panel: #161d2e;
  --panel-border: #232b3d;
  --text: #e6e9ef;
  --text-dim: #93a0b4;
  --accent: #6ea8fe;
  --accent-2: #8b5cf6;
  --green: #34d399;
  --green-bg: rgba(52, 211, 153, 0.12);
  --red: #f87171;
  --red-bg: rgba(248, 113, 113, 0.12);
  --amber: #fbbf24;
  --amber-bg: rgba(251, 191, 36, 0.12);
  --gray: #9ca3af;
  --gray-bg: rgba(156, 163, 175, 0.12);
  --shadow: 0 8px 24px rgba(0,0,0,0.35);
  --radius: 14px;
  --mono: "Cascadia Code", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  --sans: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
}
html[data-theme="light"] {
  --bg: #f4f6fb;
  --bg-alt: #ffffff;
  --panel: #ffffff;
  --panel-border: #e2e6ef;
  --text: #1a2233;
  --text-dim: #5b6577;
  --shadow: 0 8px 24px rgba(30,41,59,0.08);
  --green-bg: rgba(16, 163, 96, 0.10);
  --red-bg: rgba(220, 38, 38, 0.08);
  --amber-bg: rgba(217, 119, 6, 0.10);
  --gray-bg: rgba(107, 114, 128, 0.08);
}


* { box-sizing: border-box; }


body {
  margin: 0;
  background: radial-gradient(1200px 600px at 20% -10%, rgba(110,168,254,0.08), transparent),
              radial-gradient(1000px 600px at 100% 0%, rgba(139,92,246,0.08), transparent),
              var(--bg);
  color: var(--text);
  font-family: var(--sans);
  line-height: 1.45;
  min-height: 100vh;
}


.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 24px;
  background: linear-gradient(135deg, rgba(110,168,254,0.14), rgba(139,92,246,0.14)), var(--bg-alt);
  border-bottom: 1px solid var(--panel-border);
  flex-wrap: wrap;
  backdrop-filter: blur(6px);
}


.topbar-left { display: flex; align-items: center; gap: 14px; }
.logo {
  width: 40px; height: 40px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; color: #0b0f19; font-weight: bold;
  box-shadow: var(--shadow);
}
.titles h1 { font-size: 17px; margin: 0; letter-spacing: 0.2px; }
.subtitle { margin: 2px 0 0; font-size: 12.5px; color: var(--text-dim); }


.topbar-right { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 3px; }
.field label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--text-dim); }
select, input[type="text"] {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: var(--sans);
  min-width: 180px;
  outline: none;
}
select:focus, input[type="text"]:focus { border-color: var(--accent); }
.search-field input { min-width: 220px; }


.icon-btn {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  color: var(--text);
  border-radius: 8px;
  width: 34px; height: 34px;
  font-size: 16px;
  cursor: pointer;
  align-self: flex-end;
}
.icon-btn:hover { border-color: var(--accent); }


/* --- Multi-select dropdown --- */
.multi-select { position: relative; }
.multi-select-trigger {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: var(--panel); color: var(--text);
  border: 1px solid var(--panel-border); border-radius: 8px;
  padding: 7px 10px; font-size: 13px; cursor: pointer;
  min-width: 240px; user-select: none;
}
.multi-select-trigger:focus { border-color: var(--accent); outline: none; }
.ms-chevron { transition: transform 0.2s ease; font-size: 11px; color: var(--text-dim); }
.multi-select-dropdown.open ~ .multi-select-trigger .ms-chevron,
.multi-select.open .ms-chevron { transform: rotate(180deg); }
.multi-select-dropdown {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0;
  background: var(--panel); border: 1px solid var(--panel-border);
  border-radius: 10px; z-index: 20;
  box-shadow: var(--shadow);
  max-height: 340px; overflow-y: auto;
  display: none;
}
.multi-select-dropdown.open { display: block; }
.ms-actions {
  display: flex; gap: 6px; padding: 8px 10px;
  border-bottom: 1px solid var(--panel-border);
  position: sticky; top: 0; background: var(--panel); z-index: 1;
}
.ms-btn {
  background: var(--panel-border); border: none; color: var(--text);
  border-radius: 6px; padding: 4px 12px; font-size: 11px;
  cursor: pointer; font-family: var(--sans); transition: all 0.15s;
}
.ms-btn:hover { background: var(--accent); color: #0b0f19; }
.ms-options { padding: 4px 0; }
.ms-option {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; cursor: pointer; font-size: 13px;
  transition: background 0.1s;
}
.ms-option:hover { background: var(--gray-bg); }
.ms-option input[type="checkbox"] {
  accent-color: var(--accent); width: 15px; height: 15px;
  cursor: pointer; flex: none;
}
.ms-option-label {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  flex: 1; min-width: 0;
}
#reportSelectedText {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  flex: 1; min-width: 0;
}


/* --- Tab bar --- */
.tab-bar {
  display: flex; gap: 0; max-width: 1180px; margin: 0 auto;
  padding: 0 24px; padding-top: 12px;
}
.tab {
  background: var(--bg-alt); border: 1px solid var(--panel-border);
  border-bottom: 2px solid transparent; color: var(--text-dim);
  padding: 10px 22px; font-size: 13px; cursor: pointer;
  border-radius: 10px 10px 0 0; font-family: var(--sans);
  transition: all 0.2s; margin-right: -1px;
}
.tab:hover { color: var(--text); background: var(--panel); }
.tab.active {
  background: var(--panel); color: var(--accent);
  border-bottom-color: var(--accent); font-weight: 600;
  z-index: 1;
}


/* --- Report badge --- */
.report-badge {
  font-family: var(--sans); font-size: 10px; font-weight: 600;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #0b0f19; padding: 2px 10px; border-radius: 10px;
  margin-left: auto; flex: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 220px; letter-spacing: 0.2px;
}


main { max-width: 1180px; margin: 0 auto; padding: 20px 24px 60px; }


.meta-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}
.meta-item { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.meta-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--text-dim); }
.meta-value { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: var(--mono); font-size: 12px; }


.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  margin-bottom: 10px;
}
.card {
  display: flex; align-items: center; gap: 14px;
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: 16px 18px;
  box-shadow: var(--shadow);
}
.card-icon {
  width: 42px; height: 42px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: bold;
}
.card-added .card-icon { background: var(--green-bg); color: var(--green); }
.card-deleted .card-icon { background: var(--red-bg); color: var(--red); }
.card-modified .card-icon { background: var(--amber-bg); color: var(--amber); }
.card-unchanged .card-icon { background: var(--gray-bg); color: var(--gray); }
.card-count { font-size: 24px; font-weight: 700; line-height: 1; }
.card-label { font-size: 12px; color: var(--text-dim); margin-top: 2px; }


.bar-wrap { margin-bottom: 22px; }
.status-bar {
  display: flex; height: 8px; border-radius: 6px; overflow: hidden;
  background: var(--panel-border);
}
.status-seg { height: 100%; transition: width 0.3s ease; }
.seg-added { background: var(--green); }
.seg-deleted { background: var(--red); }
.seg-modified { background: var(--amber); }
.seg-unchanged { background: var(--gray); }


.empty-state {
  text-align: center; padding: 48px 20px; color: var(--text-dim);
  background: var(--panel); border: 1px dashed var(--panel-border); border-radius: var(--radius);
}
.empty-icon { font-size: 32px; color: var(--green); margin-bottom: 8px; }


.panel {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius);
  padding: 16px 18px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}
.panel-title {
  font-size: 14px; margin: 0 0 10px; display: flex; align-items: center; gap: 8px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.added-title { color: var(--green); }
.deleted-title { color: var(--red); }
.modified-title { color: var(--amber); }
.panel-count { font-size: 11px; color: var(--text-dim); text-transform: none; letter-spacing: 0; }


.path-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.path-list li {
  font-family: var(--mono); font-size: 12.5px;
  padding: 8px 10px; border-radius: 8px;
  display: flex; align-items: center; gap: 8px;
  border: 1px solid var(--panel-border);
}
.path-list .type-badge {
  font-family: var(--sans); font-size: 10px; text-transform: uppercase;
  padding: 2px 6px; border-radius: 5px; color: var(--text-dim);
  background: var(--gray-bg); flex: none;
}
#addedList li { background: var(--green-bg); }
#deletedList li { background: var(--red-bg); }


.modified-list { display: flex; flex-direction: column; gap: 10px; }
.mod-item {
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  background: var(--bg-alt);
  overflow: hidden;
}
.mod-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 10px 14px; cursor: pointer; user-select: none;
}
.mod-header:hover { background: var(--amber-bg); }
.mod-path { font-family: var(--mono); font-size: 12.5px; word-break: break-all; }
.mod-fields { font-size: 11px; color: var(--text-dim); margin-top: 3px; }
.mod-chevron { transition: transform 0.2s ease; color: var(--text-dim); flex: none; }
.mod-item.open .mod-chevron { transform: rotate(90deg); }
.mod-body { display: none; padding: 0 14px 14px; }
.mod-item.open .mod-body { display: block; }


table.change-table { width: 100%; border-collapse: collapse; margin: 6px 0 10px; font-size: 12.5px; }
table.change-table th, table.change-table td {
  text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--panel-border);
}
table.change-table th { color: var(--text-dim); font-weight: 600; font-size: 11px; text-transform: uppercase; }
table.change-table td.val-old { color: var(--red); font-family: var(--mono); }
table.change-table td.val-new { color: var(--green); font-family: var(--mono); }
table.change-table td.field-name { color: var(--text); font-weight: 500; }


.note-box {
  background: var(--amber-bg); color: var(--amber);
  border-radius: 8px; padding: 8px 12px; font-size: 12.5px; margin: 6px 0 10px;
}


.diff-box {
  font-family: var(--mono); font-size: 12px;
  background: #05070d;
  color: #d7dee8;
  border-radius: 8px;
  padding: 10px 0;
  overflow-x: auto;
  border: 1px solid var(--panel-border);
}
html[data-theme="light"] .diff-box { background: #0f172a; color: #e5eefc; }
.diff-line { padding: 1px 14px; white-space: pre; }
.diff-add { background: rgba(52, 211, 153, 0.16); color: #86efac; }
.diff-del { background: rgba(248, 113, 113, 0.16); color: #fca5a5; }
.diff-hunk { color: #a78bfa; }
.diff-file { color: #93a0b4; }


.hidden-by-search { display: none !important; }


/* --- Config panel styles --- */
.config-section { margin-bottom: 18px; }
.config-title {
  color: var(--accent); display: flex;
  align-items: center; justify-content: space-between;
}
.config-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label {
  font-size: 10.5px; text-transform: uppercase;
  letter-spacing: 0.5px; color: var(--text-dim); font-weight: 500;
}
.form-group input[type="text"],
.form-group input[type="number"] {
  background: var(--bg); color: var(--text);
  border: 1px solid var(--panel-border); border-radius: 8px;
  padding: 9px 12px; font-size: 13px; font-family: var(--mono);
  outline: none; transition: border-color 0.15s;
}
.form-group input:focus { border-color: var(--accent); }
.form-row {
  display: flex; gap: 24px; align-items: center;
  margin: 10px 0;
}
.toggle-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 13px; color: var(--text); cursor: pointer;
  user-select: none;
}
.toggle-label input[type="checkbox"] {
  accent-color: var(--accent); width: 16px; height: 16px; cursor: pointer;
}


/* --- Buttons --- */
.btn {
  background: var(--panel-border); border: 1px solid transparent;
  color: var(--text); border-radius: 8px;
  padding: 8px 18px; font-size: 13px; cursor: pointer;
  font-family: var(--sans); transition: all 0.15s;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn:hover { filter: brightness(1.15); }
.btn:active { transform: scale(0.97); }
.btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #0b0f19; font-weight: 600; }
.btn-secondary { background: var(--panel-border); color: var(--text); }
.btn-accent { background: var(--accent); color: #0b0f19; font-weight: 600; }
.btn-danger { background: var(--red-bg); color: var(--red); border-color: rgba(248,113,113,0.3); }
.btn-danger:hover { background: var(--red); color: #0b0f19; }
.btn-sm { padding: 5px 14px; font-size: 12px; border-radius: 7px; }
.btn-xs { padding: 3px 10px; font-size: 11px; border-radius: 6px; }


/* --- Path cards --- */
.paths-list { display: flex; flex-direction: column; gap: 8px; }
.paths-empty {
  text-align: center; color: var(--text-dim);
  padding: 24px; font-size: 13px; font-style: italic;
}
.path-card {
  background: var(--bg); border: 1px solid var(--panel-border);
  border-radius: 10px; padding: 12px 16px;
  transition: border-color 0.15s;
}
.path-card:hover { border-color: var(--accent); }
.path-card-header {
  display: flex; align-items: center;
  justify-content: space-between; gap: 12px;
}
.path-card-path {
  font-family: var(--mono); font-size: 13px;
  word-break: break-all; color: var(--text);
}
.path-card-actions { display: flex; gap: 6px; flex: none; }
.path-card-meta {
  display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap;
}
.path-tag {
  font-size: 10px; text-transform: uppercase; font-weight: 500;
  padding: 2px 8px; border-radius: 6px;
  background: var(--gray-bg); color: var(--text-dim);
  letter-spacing: 0.3px;
}


/* --- Modal --- */
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.6); z-index: 100;
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(4px);
}
.modal {
  background: var(--panel); border: 1px solid var(--panel-border);
  border-radius: var(--radius); width: 92%; max-width: 580px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  max-height: 90vh; overflow-y: auto;
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px; border-bottom: 1px solid var(--panel-border);
}
.modal-header h3 { margin: 0; font-size: 16px; color: var(--text); }
.modal-close {
  background: none; border: none; color: var(--text-dim);
  font-size: 24px; cursor: pointer; padding: 0; line-height: 1;
  transition: color 0.15s;
}
.modal-close:hover { color: var(--red); }
.modal-body { padding: 18px 22px; }
.modal-footer {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 14px 22px; border-top: 1px solid var(--panel-border);
}


/* --- Exceptions editor --- */
.exc-header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.exc-header label { margin: 0; }
.exceptions-list { display: flex; flex-direction: column; gap: 8px; }
.exception-row {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  background: var(--bg); border: 1px solid var(--panel-border);
  border-radius: 8px; padding: 8px 10px;
}
.exception-row input[type="text"] {
  background: var(--panel); color: var(--text);
  border: 1px solid var(--panel-border); border-radius: 6px;
  padding: 6px 8px; font-size: 12px; font-family: var(--mono);
  flex: 1; min-width: 100px; outline: none;
}
.exception-row input:focus { border-color: var(--accent); }


/* --- Toast notifications --- */
.toast-container {
  position: fixed; top: 76px; right: 20px; z-index: 200;
  display: flex; flex-direction: column; gap: 8px;
  pointer-events: none;
}
.toast {
  background: var(--panel); border: 1px solid var(--panel-border);
  border-radius: 10px; padding: 12px 20px;
  font-size: 13px; box-shadow: 0 12px 40px rgba(0,0,0,0.4);
  animation: toastIn 0.3s ease;
  max-width: 380px; pointer-events: auto;
}
.toast-success { border-left: 4px solid var(--green); }
.toast-error { border-left: 4px solid var(--red); }
.toast-info { border-left: 4px solid var(--accent); }
@keyframes toastIn {
  from { transform: translateX(120%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}


/* --- Config actions bar --- */
.config-actions {
  display: flex; gap: 10px; justify-content: flex-end;
  padding: 16px 0;
  border-top: 1px solid var(--panel-border);
  margin-top: 4px;
}


.footer {
  text-align: center; color: var(--text-dim); font-size: 11.5px;
  padding: 20px; border-top: 1px solid var(--panel-border);
}


@media (max-width: 640px) {
  .topbar { flex-direction: column; align-items: stretch; }
  .topbar-right { justify-content: space-between; }
  .multi-select-trigger, .search-field input { min-width: 0; width: 100%; }
  .tab-bar { padding: 0 12px; }
  .tab { padding: 8px 14px; font-size: 12px; }
  .config-form { grid-template-columns: 1fr; }
  .form-row { flex-direction: column; gap: 10px; align-items: flex-start; }
}
"""
JS = """
(function () {
  'use strict';

  var dataEl = document.getElementById('report-data');
  var reports = JSON.parse(dataEl.textContent || '[]');
  var selectedIndices = [];
  var configData = null;
  var editingPathIndex = -1;

  /* --- Element refs --- */
  var els = {
    subtitle: document.getElementById('subtitle'),
    metaServerId: document.getElementById('metaServerId'),
    metaHostname: document.getElementById('metaHostname'),
    metaGenerated: document.getElementById('metaGenerated'),
    metaPrev: document.getElementById('metaPrev'),
    metaCurr: document.getElementById('metaCurr'),
    countAdded: document.getElementById('countAdded'),
    countDeleted: document.getElementById('countDeleted'),
    countModified: document.getElementById('countModified'),
    countUnchanged: document.getElementById('countUnchanged'),
    segAdded: document.querySelector('.seg-added'),
    segDeleted: document.querySelector('.seg-deleted'),
    segModified: document.querySelector('.seg-modified'),
    segUnchanged: document.querySelector('.seg-unchanged'),
    emptyState: document.getElementById('emptyState'),
    addedSection: document.getElementById('addedSection'),
    deletedSection: document.getElementById('deletedSection'),
    modifiedSection: document.getElementById('modifiedSection'),
    addedList: document.getElementById('addedList'),
    deletedList: document.getElementById('deletedList'),
    modifiedList: document.getElementById('modifiedList'),
    addedTitleCount: document.getElementById('addedTitleCount'),
    deletedTitleCount: document.getElementById('deletedTitleCount'),
    modifiedTitleCount: document.getElementById('modifiedTitleCount'),
    searchBox: document.getElementById('searchBox'),
    themeToggle: document.getElementById('themeToggle'),
    reportTrigger: document.getElementById('reportTrigger'),
    reportDropdown: document.getElementById('reportDropdown'),
    reportSelectedText: document.getElementById('reportSelectedText'),
    reportCheckboxes: document.getElementById('reportCheckboxes')
  };

  /* --- Utilities --- */
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function showToast(message, type) {
    var container = document.getElementById('toastContainer');
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + (type || 'info');
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function() {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(120%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 350);
    }, 3500);
  }

  /* --- Theme --- */
  var THEME_KEY = 'server_snapshot_dashboard_theme';
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    els.themeToggle.innerHTML = theme === 'dark' ? '&#9788;' : '&#9789;';
  }
  els.themeToggle.addEventListener('click', function () {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  });
  var savedTheme = null;
  try { savedTheme = localStorage.getItem(THEME_KEY); } catch (e) {}
  applyTheme(savedTheme || 'dark');

  /* ================================================================
   *  MULTI-SELECT DROPDOWN
   * ================================================================ */

  function populateMultiSelect() {
    els.reportCheckboxes.innerHTML = reports.map(function (entry, i) {
      return '<label class="ms-option">' +
        '<input type="checkbox" value="' + i + '">' +
        '<span class="ms-option-label" title="' + escapeHtml(entry.label) + '">' + escapeHtml(entry.label) + '</span>' +
        '</label>';
    }).join('');
  }

  function getSelectedIndices() {
    var checks = els.reportCheckboxes.querySelectorAll('input[type="checkbox"]');
    var indices = [];
    for (var i = 0; i < checks.length; i++) {
      if (checks[i].checked) indices.push(parseInt(checks[i].value, 10));
    }
    return indices;
  }

  function updateTriggerText() {
    var indices = getSelectedIndices();
    var n = indices.length;
    if (n === 0) {
      els.reportSelectedText.textContent = 'Select reports\\u2026';
    } else if (n === 1) {
      els.reportSelectedText.textContent = reports[indices[0]].label;
    } else if (n === reports.length) {
      els.reportSelectedText.textContent = 'All reports (' + n + ')';
    } else {
      els.reportSelectedText.textContent = n + ' reports selected';
    }
  }

  function toggleDropdown() {
    els.reportDropdown.classList.toggle('open');
  }

  function onSelectionChange() {
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    if (selectedIndices.length > 0) {
      renderMultiple(selectedIndices);
    }
  }

  /* Trigger click */
  els.reportTrigger.addEventListener('click', function (e) {
    e.stopPropagation();
    toggleDropdown();
  });

  /* Close on outside click */
  document.addEventListener('click', function (e) {
    var ms = document.getElementById('reportMultiSelect');
    if (!ms.contains(e.target)) {
      els.reportDropdown.classList.remove('open');
    }
  });

  /* Checkbox change (event delegation) */
  els.reportCheckboxes.addEventListener('change', function () {
    onSelectionChange();
  });

  /* Select All / Deselect All */
  document.getElementById('selectAll').addEventListener('click', function (e) {
    e.stopPropagation();
    var checks = els.reportCheckboxes.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < checks.length; i++) checks[i].checked = true;
    onSelectionChange();
  });
  document.getElementById('deselectAll').addEventListener('click', function (e) {
    e.stopPropagation();
    var checks = els.reportCheckboxes.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < checks.length; i++) checks[i].checked = false;
    onSelectionChange();
  });

  /* ================================================================
   *  REPORT RENDERING (merged multi-report view)
   * ================================================================ */

  function renderDiffLines(lines) {
    return (lines || []).map(function (line) {
      var cls = 'diff-line';
      if (line.startsWith('+++') || line.startsWith('---')) cls += ' diff-file';
      else if (line.startsWith('@@')) cls += ' diff-hunk';
      else if (line.startsWith('+')) cls += ' diff-add';
      else if (line.startsWith('-')) cls += ' diff-del';
      return '<div class="' + cls + '">' + escapeHtml(line.replace(/\\n$/, '')) + '</div>';
    }).join('');
  }

  function fieldRows(changes) {
    return Object.keys(changes || {}).map(function (key) {
      var v = changes[key];
      return '<tr>' +
        '<td class="field-name">' + escapeHtml(key) + '</td>' +
        '<td class="val-old">' + escapeHtml(v.old) + '</td>' +
        '<td class="val-new">' + escapeHtml(v['new']) + '</td>' +
        '</tr>';
    }).join('');
  }

  function renderMultiple(indices) {
    if (!indices.length) return;

    var allAdded = [];
    var allDeleted = [];
    var allModified = [];
    var totalUnchanged = 0;
    var serverIds = {};
    var hostnames = {};
    var generatedAts = [];
    var showBadge = indices.length > 1;

    for (var idx = 0; idx < indices.length; idx++) {
      var i = indices[idx];
      var entry = reports[i];
      if (!entry) continue;
      var r = entry.data;
      var label = entry.label;
      var summary = r.summary || {};

      (r.added || []).forEach(function (item) {
        allAdded.push({ path: item.path, type: item.type, _report: label });
      });
      (r.deleted || []).forEach(function (item) {
        allDeleted.push({ path: item.path, type: item.type, _report: label });
      });
      (r.modified || []).forEach(function (item) {
        allModified.push({
          path: item.path, changes: item.changes,
          content_diff: item.content_diff, content_note: item.content_note,
          _report: label
        });
      });
      totalUnchanged += summary.unchanged || 0;
      serverIds[r.server_id || ''] = true;
      hostnames[r.hostname || ''] = true;
      if (r.generated_at) generatedAts.push(r.generated_at);
    }

    /* Meta bar */
    els.metaServerId.textContent = Object.keys(serverIds).join(', ') || '\\u2014';
    els.metaHostname.textContent = Object.keys(hostnames).join(', ') || '\\u2014';

    if (indices.length === 1) {
      var sr = reports[indices[0]].data;
      els.metaGenerated.textContent = sr.generated_at || '\\u2014';
      els.metaPrev.textContent = sr.previous_snapshot || '(none - baseline run)';
      els.metaCurr.textContent = sr.current_snapshot || '\\u2014';
      els.subtitle.textContent = reports[indices[0]].label;
    } else {
      generatedAts.sort();
      els.metaGenerated.textContent = generatedAts[0] + ' \\u2192 ' + generatedAts[generatedAts.length - 1];
      els.metaPrev.textContent = '(' + indices.length + ' reports selected)';
      els.metaCurr.textContent = '(' + indices.length + ' reports selected)';
      els.subtitle.textContent = indices.length + ' reports selected';
    }

    /* Summary cards */
    els.countAdded.textContent = allAdded.length;
    els.countDeleted.textContent = allDeleted.length;
    els.countModified.textContent = allModified.length;
    els.countUnchanged.textContent = totalUnchanged;

    /* Status bar */
    var total = allAdded.length + allDeleted.length + allModified.length + totalUnchanged;
    function pct(n) { return total > 0 ? (100 * n / total).toFixed(2) + '%' : '0%'; }
    els.segAdded.style.width = pct(allAdded.length);
    els.segDeleted.style.width = pct(allDeleted.length);
    els.segModified.style.width = pct(allModified.length);
    els.segUnchanged.style.width = pct(totalUnchanged);

    /* Sections visibility */
    var hasChanges = allAdded.length + allDeleted.length + allModified.length > 0;
    els.emptyState.style.display = hasChanges ? 'none' : '';
    els.addedSection.style.display = allAdded.length ? '' : 'none';
    els.deletedSection.style.display = allDeleted.length ? '' : 'none';
    els.modifiedSection.style.display = allModified.length ? '' : 'none';

    els.addedTitleCount.textContent = '(' + allAdded.length + ')';
    els.deletedTitleCount.textContent = '(' + allDeleted.length + ')';
    els.modifiedTitleCount.textContent = '(' + allModified.length + ')';

    /* Added list */
    els.addedList.innerHTML = allAdded.map(function (item) {
      var badge = showBadge ? '<span class="report-badge" title="' + escapeHtml(item._report) + '">' + escapeHtml(item._report) + '</span>' : '';
      return '<li data-path="' + escapeHtml(item.path.toLowerCase()) + '">' +
        '<span class="type-badge">' + escapeHtml(item.type || '?') + '</span>' +
        '<span>' + escapeHtml(item.path) + '</span>' + badge + '</li>';
    }).join('');

    /* Deleted list */
    els.deletedList.innerHTML = allDeleted.map(function (item) {
      var badge = showBadge ? '<span class="report-badge" title="' + escapeHtml(item._report) + '">' + escapeHtml(item._report) + '</span>' : '';
      return '<li data-path="' + escapeHtml(item.path.toLowerCase()) + '">' +
        '<span class="type-badge">' + escapeHtml(item.type || '?') + '</span>' +
        '<span>' + escapeHtml(item.path) + '</span>' + badge + '</li>';
    }).join('');

    /* Modified list */
    els.modifiedList.innerHTML = allModified.map(function (item, mi) {
      var fieldNames = Object.keys(item.changes || {}).join(', ');
      var badge = showBadge ? '<span class="report-badge" title="' + escapeHtml(item._report) + '">' + escapeHtml(item._report) + '</span>' : '';
      var body = '';
      if (item.changes && Object.keys(item.changes).length) {
        body += '<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th></tr></thead>' +
          '<tbody>' + fieldRows(item.changes) + '</tbody></table>';
      }
      if (item.content_note) {
        body += '<div class="note-box">' + escapeHtml(item.content_note) + '</div>';
      }
      if (item.content_diff && item.content_diff.length) {
        body += '<div class="diff-box">' + renderDiffLines(item.content_diff) + '</div>';
      }
      return '<div class="mod-item" data-path="' + escapeHtml(item.path.toLowerCase()) + '" data-idx="' + mi + '">' +
        '<div class="mod-header">' +
        '<div><div class="mod-path">' + escapeHtml(item.path) + '</div>' +
        '<div class="mod-fields">changed: ' + escapeHtml(fieldNames || '(content only)') + '</div></div>' +
        badge +
        '<div class="mod-chevron">&#9656;</div></div>' +
        '<div class="mod-body">' + body + '</div></div>';
    }).join('');

    applySearchFilter();
  }

  function applySearchFilter() {
    var q = (els.searchBox.value || '').trim().toLowerCase();
    var nodes = document.querySelectorAll('[data-path]');
    for (var i = 0; i < nodes.length; i++) {
      var match = !q || nodes[i].getAttribute('data-path').indexOf(q) !== -1;
      if (match) nodes[i].classList.remove('hidden-by-search');
      else nodes[i].classList.add('hidden-by-search');
    }
  }

  /* Modified item toggle (event delegation) */
  document.addEventListener('click', function (e) {
    var header = e.target.closest('.mod-header');
    if (header) header.parentElement.classList.toggle('open');
  });

  els.searchBox.addEventListener('input', applySearchFilter);

  /* ================================================================
   *  TAB SWITCHING
   * ================================================================ */

  function switchTab(tabName) {
    var reportsView = document.getElementById('reportsView');
    var configView = document.getElementById('configView');
    var tabs = document.querySelectorAll('.tab');
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].getAttribute('data-tab') === tabName) tabs[i].classList.add('active');
      else tabs[i].classList.remove('active');
    }
    if (tabName === 'reports') {
      reportsView.style.display = '';
      configView.style.display = 'none';
    } else {
      reportsView.style.display = 'none';
      configView.style.display = '';
      if (!configData) loadConfig();
    }
  }

  var tabBtns = document.querySelectorAll('.tab');
  for (var ti = 0; ti < tabBtns.length; ti++) {
    (function (btn) {
      btn.addEventListener('click', function () {
        switchTab(btn.getAttribute('data-tab'));
      });
    })(tabBtns[ti]);
  }

  /* ================================================================
   *  CONFIG CRUD
   * ================================================================ */

  function loadConfig() {
    fetch('/api/config')
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        configData = data;
        document.getElementById('configUnavailable').style.display = 'none';
        document.getElementById('configContent').style.display = '';
        populateConfigForm(data);
      })
      .catch(function () {
        document.getElementById('configUnavailable').style.display = '';
        document.getElementById('configContent').style.display = 'none';
      });
  }

  function populateConfigForm(cfg) {
    document.getElementById('cfgServerId').value = cfg.server_id || '';
    document.getElementById('cfgHostname').value = cfg.hostname || '';
    document.getElementById('cfgSnapshotDir').value = cfg.snapshot_dir || '';
    document.getElementById('cfgReportDir').value = cfg.report_dir || '';
    document.getElementById('cfgLogFile').value = cfg.log_file || '';
    document.getElementById('cfgMaxContentSize').value = cfg.max_content_size_bytes || 5242880;
    document.getElementById('cfgRetentionCount').value = cfg.retention_count != null ? cfg.retention_count : 30;

    var alerting = cfg.alerting || {};
    document.getElementById('cfgAlertCommand').value = alerting.command || '';
    document.getElementById('cfgWebhookUrl').value = alerting.webhook_url || '';

    var dash = cfg.dashboard || {};
    document.getElementById('cfgDashHost').value = dash.host || '127.0.0.1';
    document.getElementById('cfgDashPort').value = dash.port || 8080;

    renderPaths(cfg.paths || []);
  }

  function gatherConfigFromForm() {
    var cfg = {};
    cfg.server_id = document.getElementById('cfgServerId').value.trim();
    var hn = document.getElementById('cfgHostname').value.trim();
    if (hn) cfg.hostname = hn;
    cfg.snapshot_dir = document.getElementById('cfgSnapshotDir').value.trim();
    cfg.report_dir = document.getElementById('cfgReportDir').value.trim();
    var lf = document.getElementById('cfgLogFile').value.trim();
    if (lf) cfg.log_file = lf;
    cfg.max_content_size_bytes = parseInt(document.getElementById('cfgMaxContentSize').value, 10) || 5242880;
    cfg.retention_count = parseInt(document.getElementById('cfgRetentionCount').value, 10);
    if (isNaN(cfg.retention_count)) cfg.retention_count = 30;

    cfg.paths = (configData && configData.paths) ? configData.paths : [];

    var alertCmd = document.getElementById('cfgAlertCommand').value.trim();
    var webhookUrl = document.getElementById('cfgWebhookUrl').value.trim();
    cfg.alerting = {
      command: alertCmd || null,
      webhook_url: webhookUrl || null
    };

    cfg.dashboard = {
      host: document.getElementById('cfgDashHost').value.trim() || '127.0.0.1',
      port: parseInt(document.getElementById('cfgDashPort').value, 10) || 8080
    };

    return cfg;
  }

  function saveConfig() {
    var cfg = gatherConfigFromForm();

    /* Client-side validation */
    if (!cfg.server_id) { showToast('Server ID is required', 'error'); return; }
    if (!cfg.snapshot_dir || !cfg.snapshot_dir.startsWith('/')) {
      showToast('Snapshot directory must be an absolute path (starts with /)', 'error'); return;
    }
    if (!cfg.report_dir || !cfg.report_dir.startsWith('/')) {
      showToast('Report directory must be an absolute path (starts with /)', 'error'); return;
    }
    if (!cfg.paths || !cfg.paths.length) {
      showToast('At least one monitored path is required', 'error'); return;
    }

    var saveBtn = document.getElementById('saveConfigBtn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving\\u2026';

    fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg)
    })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (data.error) {
        showToast(data.error, 'error');
      } else {
        configData = cfg;
        showToast(data.message || 'Configuration saved', 'success');
      }
    })
    .catch(function (err) {
      showToast('Failed to save: ' + err.message, 'error');
    })
    .finally(function () {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '&#128190; Save Configuration';
    });
  }

  function renderPaths(paths) {
    var container = document.getElementById('pathsList');
    var emptyEl = document.getElementById('pathsEmpty');

    if (!paths || !paths.length) {
      container.innerHTML = '';
      emptyEl.style.display = '';
      return;
    }
    emptyEl.style.display = 'none';

    container.innerHTML = paths.map(function (p, i) {
      var excCount = (p.exceptions || []).length;
      var tags = [];
      if (p.recursive !== false) tags.push('recursive');
      if (p.include_content) tags.push('content');
      if (excCount) tags.push(excCount + ' exception' + (excCount > 1 ? 's' : ''));

      return '<div class="path-card" data-path-index="' + i + '">' +
        '<div class="path-card-header">' +
        '<span class="path-card-path">' + escapeHtml(p.path) + '</span>' +
        '<div class="path-card-actions">' +
        '<button type="button" class="btn btn-xs btn-secondary edit-path-btn" data-index="' + i + '">Edit</button>' +
        '<button type="button" class="btn btn-xs btn-danger delete-path-btn" data-index="' + i + '">Delete</button>' +
        '</div></div>' +
        '<div class="path-card-meta">' + tags.map(function (t) {
          return '<span class="path-tag">' + escapeHtml(t) + '</span>';
        }).join('') + '</div></div>';
    }).join('');
  }

  /* --- Path card event delegation --- */
  document.getElementById('pathsList').addEventListener('click', function (e) {
    var editBtn = e.target.closest('.edit-path-btn');
    var deleteBtn = e.target.closest('.delete-path-btn');
    if (editBtn) openPathModal(parseInt(editBtn.getAttribute('data-index'), 10));
    if (deleteBtn) deletePath(parseInt(deleteBtn.getAttribute('data-index'), 10));
  });

  /* ================================================================
   *  PATH MODAL
   * ================================================================ */

  function openPathModal(index) {
    editingPathIndex = index;
    var modal = document.getElementById('pathModal');
    var title = document.getElementById('pathModalTitle');

    if (index >= 0 && configData && configData.paths && configData.paths[index]) {
      title.textContent = 'Edit Monitored Path';
      var p = configData.paths[index];
      document.getElementById('modalPath').value = p.path || '';
      document.getElementById('modalRecursive').checked = p.recursive !== false;
      document.getElementById('modalIncludeContent').checked = !!p.include_content;
      renderExceptions(p.exceptions || []);
    } else {
      title.textContent = 'Add Monitored Path';
      document.getElementById('modalPath').value = '';
      document.getElementById('modalRecursive').checked = true;
      document.getElementById('modalIncludeContent').checked = false;
      renderExceptions([]);
    }

    modal.style.display = 'flex';
  }

  function closePathModal() {
    document.getElementById('pathModal').style.display = 'none';
    editingPathIndex = -1;
  }

  function savePathModal() {
    var pathVal = document.getElementById('modalPath').value.trim();
    if (!pathVal) { showToast('Path is required', 'error'); return; }
    if (!pathVal.startsWith('/')) { showToast('Path must be absolute (start with /)', 'error'); return; }

    var entry = {
      path: pathVal,
      recursive: document.getElementById('modalRecursive').checked,
      include_content: document.getElementById('modalIncludeContent').checked
    };

    /* Gather exceptions */
    var excRows = document.querySelectorAll('#modalExceptions .exception-row');
    var exceptions = [];
    for (var ei = 0; ei < excRows.length; ei++) {
      var row = excRows[ei];
      var excPath = row.querySelector('.exc-path').value.trim();
      var excPattern = row.querySelector('.exc-pattern').value.trim();
      var excContent = row.querySelector('.exc-content').checked;
      if (excPath || excPattern) {
        var exc = { include_content: excContent };
        if (excPath) exc.path = excPath;
        else exc.pattern = excPattern;
        exceptions.push(exc);
      }
    }
    if (exceptions.length) entry.exceptions = exceptions;

    if (!configData) configData = { paths: [] };
    if (!configData.paths) configData.paths = [];

    if (editingPathIndex >= 0) {
      configData.paths[editingPathIndex] = entry;
      showToast('Path updated (save to persist)', 'info');
    } else {
      configData.paths.push(entry);
      showToast('Path added (save to persist)', 'info');
    }

    renderPaths(configData.paths);
    closePathModal();
  }

  function deletePath(index) {
    if (!configData || !configData.paths || !configData.paths[index]) return;
    var pathName = configData.paths[index].path;
    if (!confirm('Delete monitored path: ' + pathName + '?')) return;
    configData.paths.splice(index, 1);
    renderPaths(configData.paths);
    showToast('Path removed (save to persist)', 'info');
  }

  function renderExceptions(exceptions) {
    var container = document.getElementById('modalExceptions');
    container.innerHTML = (exceptions || []).map(function (exc) {
      return '<div class="exception-row">' +
        '<input type="text" class="exc-path" placeholder="Exact path" value="' + escapeHtml(exc.path || '') + '">' +
        '<input type="text" class="exc-pattern" placeholder="Glob pattern" value="' + escapeHtml(exc.pattern || '') + '">' +
        '<label class="toggle-label"><input type="checkbox" class="exc-content"' + (exc.include_content ? ' checked' : '') + '> Content</label>' +
        '<button type="button" class="btn btn-xs btn-danger remove-exc-btn">&times;</button>' +
        '</div>';
    }).join('');
  }

  function addException() {
    var container = document.getElementById('modalExceptions');
    var row = document.createElement('div');
    row.className = 'exception-row';
    row.innerHTML = '<input type="text" class="exc-path" placeholder="Exact path" value="">' +
      '<input type="text" class="exc-pattern" placeholder="Glob pattern" value="">' +
      '<label class="toggle-label"><input type="checkbox" class="exc-content"> Content</label>' +
      '<button type="button" class="btn btn-xs btn-danger remove-exc-btn">&times;</button>';
    container.appendChild(row);
  }

  /* Modal event listeners */
  document.getElementById('addPathBtn').addEventListener('click', function () { openPathModal(-1); });
  document.getElementById('pathModalSave').addEventListener('click', savePathModal);
  document.getElementById('pathModalCancel').addEventListener('click', closePathModal);
  document.getElementById('pathModalClose').addEventListener('click', closePathModal);
  document.getElementById('addExceptionBtn').addEventListener('click', addException);

  /* Close modal on overlay click */
  document.getElementById('pathModal').addEventListener('click', function (e) {
    if (e.target === this) closePathModal();
  });

  /* Remove exception (event delegation) */
  document.getElementById('modalExceptions').addEventListener('click', function (e) {
    var btn = e.target.closest('.remove-exc-btn');
    if (btn) {
      var row = btn.closest('.exception-row');
      if (row && row.parentNode) row.parentNode.removeChild(row);
    }
  });

  /* Config save / reload */
  document.getElementById('saveConfigBtn').addEventListener('click', saveConfig);
  document.getElementById('reloadConfigBtn').addEventListener('click', function () {
    configData = null;
    loadConfig();
    showToast('Configuration reloaded', 'info');
  });

  /* ================================================================
   *  INIT
   * ================================================================ */

  if (!reports.length) {
    els.subtitle.textContent = 'No report data available';
  } else {
    populateMultiSelect();
    /* Pre-select the latest report by default */
    var allChecks = els.reportCheckboxes.querySelectorAll('input[type="checkbox"]');
    if (allChecks.length) allChecks[allChecks.length - 1].checked = true;
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    renderMultiple(selectedIndices);
  }
})();
"""
def build_dashboard_html(entries: List[Dict[str, Any]], title: str) -> str:
    data_json = json.dumps(entries, sort_keys=True)
    # Defend against premature </script> termination if any monitored file's
    # content/diff happens to contain that literal substring.
    data_json = data_json.replace("</", "<\\/")
    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    out = HTML_TEMPLATE
    out = out.replace("__TITLE__", html.escape(title))
    out = out.replace("__CSS__", CSS)
    out = out.replace("__JS__", JS)
    out = out.replace("__REPORT_DATA_JSON__", data_json)
    out = out.replace("__SCRIPT_VERSION__", SCRIPT_VERSION)
    out = out.replace("__RENDERED_AT__", rendered_at)
    return out


def _report_label(path: str, report: Dict[str, Any]) -> str:
    generated_at = report.get("generated_at")
    base = os.path.splitext(os.path.basename(path))[0]
    return f"{generated_at} ({base})" if generated_at else base


def _write_html_file(path: str, content: str) -> None:
    """Write atomically (temp file + os.replace) and lock down permissions,
    since the dashboard may embed file content diffs."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".dashboard_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a modern, offline HTML dashboard from server_snapshot.py JSON reports.",
    )
    parser.add_argument("--config", help=f"Path to config.json (default lookup: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--report", help="Visualize one specific report JSON file")
    parser.add_argument("--report-dir", help="Reports directory (overrides config.json)")
    parser.add_argument("--server-id", help="Server ID (overrides config.json)")
    parser.add_argument(
        "--history", type=int, default=0,
        help="Bundle the N most recent reports into one dashboard (default: 0 = all available reports)",
    )
    parser.add_argument("--output", help="Output HTML file path (default: report_dir/dashboard/dashboard_<server_id>_<ts>.html)")
    parser.add_argument("--title", help="Custom dashboard title")
    parser.add_argument("--version", action="version", version=f"visualize_report {SCRIPT_VERSION}")
    args = parser.parse_args(argv)


    try:
        report_paths: List[str]


        if args.report:
            report_paths = [args.report]
            if not os.path.isfile(args.report):
                raise VisualizeError(f"Report file not found: {args.report}")
        else:
            report_dir = args.report_dir
            server_id = args.server_id


            if not report_dir or not server_id:
                config_path = args.config or DEFAULT_CONFIG_PATH
                config = load_minimal_config(config_path)
                report_dir = report_dir or config["report_dir"]
                server_id = server_id or config["server_id"]


            report_paths = gather_report_paths(report_dir, server_id, args.history)
            if not report_paths:
                raise VisualizeError(
                    f"No report files found matching report_{server_id}_*.json in {report_dir}"
                )


        entries = []
        for path in report_paths:
            report = load_report_file(path)
            entries.append({"file": path, "label": _report_label(path, report), "data": report})


        server_id_for_title = entries[-1]["data"].get("server_id", "unknown")
        title = args.title or f"Server Snapshot Dashboard - {server_id_for_title}"


        html_out = build_dashboard_html(entries, title)


        if args.output:
            output_path = args.output
            out_dir = os.path.dirname(os.path.abspath(output_path))
        else:
            reports_base_dir = os.path.dirname(os.path.abspath(report_paths[-1]))
            # Dedicated subfolder, kept separate from raw report/snapshot JSON,
            # so an HTTP server (serve_dashboard.py) can be pointed only at
            # rendered dashboards and never expose raw report data.
            out_dir = os.path.join(reports_base_dir, "dashboard")
            ts = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S")
            output_path = os.path.join(out_dir, f"dashboard_{server_id_for_title}_{ts}.html")


        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            try:
                os.chmod(out_dir, 0o700)
            except OSError:
                pass


        _write_html_file(output_path, html_out)


        # Also refresh a stable-name copy so a fixed URL (e.g. served by
        # serve_dashboard.py) always reflects the latest run.
        stable_path = os.path.join(out_dir, f"latest_dashboard_{server_id_for_title}.html")
        if os.path.abspath(stable_path) != os.path.abspath(output_path):
            _write_html_file(stable_path, html_out)


        print(f"Dashboard written to: {output_path}")
        print(f"Stable URL target:    {stable_path}")
        print(f"Reports included: {len(entries)}")
        return 0


    except VisualizeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
