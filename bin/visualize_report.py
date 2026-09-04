#!/usr/bin/env python3
"""
visualize_report.py
====================








Generates a modern, self-contained, fully offline HTML dashboard from one or
more server_snapshot.py JSON change reports, so drift can be reviewed visually
instead of by reading raw JSON/text. Also includes optional Application
Snapshots (binary inventory) and Network Settings tabs, a change-approval
panel wired to bin/serve_dashboard.py's /api/approve and /api/reject
endpoints, and a Configuration tab for editing config.json in-browser.








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
  visualize_report.py --config /else/serversnap/config/config.json








  # Bundle the N most recent reports for this server (0 = all available):
  visualize_report.py --config /else/serversnap/config/config.json --history 20








  # Visualize one specific report file directly (no config.json needed):
  visualize_report.py --report /else/serversnap/reports/report_web01_2026_07_29_09_54_16.json








  # Point directly at a reports directory + server_id (no config.json needed):
  visualize_report.py --report-dir ./reports --server-id web01








  # Include the Application Snapshots + Network Settings tabs:
  visualize_report.py --config ... --app-dir /bin --network-snapshot /else/serversnap/Output/config-snapshot.yaml








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








DEFAULT_CONFIG_PATH = "/else/serversnap/config/config.json"
SCRIPT_VERSION = "3.0.0"




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






def analyze_configured_paths(config_path: str) -> Dict[str, Any]:
    result = {
        "total_binaries": 0,
        "executables": [],
        "scripts": [],
        "symlinks": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


    try:
        with open(config_path, "r") as f:
            config = json.load(f)


        monitored_paths = [item["path"] for item in config.get("paths", [])]


        for path in monitored_paths:
            if not os.path.exists(path):
                continue


            # If directory, scan immediate contents
            if os.path.isdir(path):
                entries = [
                    os.path.join(path, name)
                    for name in os.listdir(path)
                ]
            else:
                entries = [path]


            for full_path in entries:
                item = {
                    "name": os.path.basename(full_path),
                    "path": full_path,
                }


                try:
                    if os.path.islink(full_path):
                        item["type"] = "symlink"
                        item["target"] = os.readlink(full_path)
                        result["symlinks"].append(item)


                    elif os.path.isfile(full_path):
                        item["type"] = "file"
                        item["size"] = os.path.getsize(full_path)
                        item["permissions"] = oct(
                            os.stat(full_path).st_mode
                        )[-3:]
                        item["mtime"] = datetime.fromtimestamp(
                            os.path.getmtime(full_path), tz=timezone.utc
                        ).isoformat()


                        if full_path.endswith(
                            (".py", ".sh", ".bash")
                        ):
                            item["subtype"] = "script"
                            result["scripts"].append(item)
                        elif os.access(
                            full_path, os.X_OK
                        ):
                            item["subtype"] = "binary"
                            result["executables"].append(item)


                        result["total_binaries"] += 1


                except (OSError, PermissionError):
                    pass


    except Exception as exc:
        result["error"] = str(exc)


    return result


def load_yaml_snapshot(path: str) -> Dict[str, Any]:
    """Load and parse YAML snapshot file (simplified parser for key:value format)."""
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()








        current_section = None
        for line in lines:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue








            if line and not line.startswith((" ", "\t")) and ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and val:
                    result[key] = val
                if key and not val:
                    current_section = key
                    result[current_section] = {}
            elif line.startswith((" ", "\t")) and current_section and ":" in line:
                line_stripped = line.lstrip()
                if ":" in line_stripped:
                    key, val = line_stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'").strip("-").strip()
                    if key and val:
                        if isinstance(result[current_section], dict):
                            result[current_section][key] = val








        return result
    except (OSError, ValueError) as exc:
        raise VisualizeError(f"Failed to read/parse YAML snapshot {path}: {exc}") from exc
def parse_network_settings(yaml_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and organize network-related settings from YAML snapshot."""
    return {
        "sysctl_kernel": yaml_data.get("sysctl_kernel", {}),
        "cpu_isolation_power": yaml_data.get("cpu_isolation_power", {}),
        "irq_affinity": yaml_data.get("irq_affinity", {}),
        "nic_ethtool": yaml_data.get("nic_ethtool", {}),
        "time_synchronization": yaml_data.get("time_synchronization", {}),
        "hugepages_tuned": yaml_data.get("hugepages_tuned", {}),
    }








# ---------------------------------------------------------------------------
# HTML generation  —  templates live in public/ alongside this script
# ---------------------------------------------------------------------------




_PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")




def _read_public(filename: str) -> str:
    """Read a file from the public/ directory next to this script."""
    path = os.path.join(_PUBLIC_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise VisualizeError(
            f"Cannot read template file {path}: {exc}\n"
            "Make sure public/visualize_report.html, .css, and .js are present."
        ) from exc




def _compute_threshold_data(
    entries: List[Dict[str, Any]],
    threshold: int,
    approvals_dir: Optional[str],
    server_id: str,
) -> Dict[str, Any]:
    """Build the threshold metadata dict injected into the dashboard.


    For each report entry we compute:
        change_count = len(added) + len(deleted) + len(modified)
    and look up any existing approval decision from ReportApprovalStore.


    We also register new reports as 'pending' in the store (no-op if a
    decision has already been recorded).
    """
    store = None
    if approvals_dir:
        try:
            from report_approval_store import ReportApprovalStore  # type: ignore
            store = ReportApprovalStore(server_id, approvals_dir)
        except ImportError:
            pass


    reports_meta: Dict[str, Any] = {}
    for entry in entries:
        report = entry["data"]
        basename = os.path.basename(entry["file"]) if entry.get("file") else ""
        label = entry.get("label", basename)


        added   = len(report.get("added",    []))
        deleted = len(report.get("deleted",  []))
        modified = len(report.get("modified", []))
        change_count = added + deleted + modified
        exceeded = change_count > threshold


        is_baseline = not report.get("previous_snapshot")


        # Register in store
        if store and basename:
            try:
                # If this is the initial baseline run, auto-approve it
                if is_baseline:
                    store.set_pending(basename, label, change_count, threshold)
                    store._save({**store._load(), basename: {**store._load().get(basename, {}), "status": "approved"}})
                else:
                    store.set_pending(basename, label, change_count, threshold)
            except Exception:  # noqa: BLE001
                pass


        # Fetch persisted status (may differ from 'pending' if decided earlier)
        status = "pending"
        if store and basename:
            try:
                rec = store.get_record(basename)
                if rec:
                    status = rec.get("status", "pending")
                    exceeded = rec.get("threshold_exceeded", exceeded)
            except Exception:  # noqa: BLE001
                pass


        if basename:
            reports_meta[basename] = {
                "status": status,
                "report_label": label,
                "change_count": change_count,
                "threshold_exceeded": exceeded,
                "added": added,
                "deleted": deleted,
                "modified": modified,
            }


    return {"threshold": threshold, "reports": reports_meta}


def build_dashboard_html(
    entries: List[Dict[str, Any]], title: str,
    app_data: Optional[Dict[str, Any]] = None,
    network_data: Optional[Dict[str, Any]] = None,
    threshold_data: Optional[Dict[str, Any]] = None,
) -> str:
    data_json = json.dumps(entries, sort_keys=True)
    # Defend against premature </script> termination if any monitored file's
    # content/diff happens to contain that literal substring.
    data_json = data_json.replace("</", "<\\/")
    app_json = json.dumps(app_data or {}, sort_keys=True, default=str).replace("</", "<\\/")
    network_json = json.dumps(network_data or {}, sort_keys=True, default=str).replace("</", "<\\/")
    threshold_json = json.dumps(threshold_data or {"threshold": 0, "reports": {}}, sort_keys=True).replace("</", "<\\/")
    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


    html_template = _read_public("visualize_report.html")
    css = _read_public("visualize_report.css")
    js = _read_public("visualize_report.js")


    out = html_template
    out = out.replace("__TITLE__", html.escape(title))
    out = out.replace("__CSS__", css)
    out = out.replace("__JS__", js)
    out = out.replace("__REPORT_DATA_JSON__", data_json)
    out = out.replace("__APP_DATA_JSON__", app_json)
    out = out.replace("__NETWORK_DATA_JSON__", network_json)
    out = out.replace("__THRESHOLD_DATA_JSON__", threshold_json)
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
    parser.add_argument("--app-dir", help="Application directory to scan for the Application Snapshots tab (optional, e.g. /bin)")
    parser.add_argument("--network-snapshot", help="Path to a YAML network snapshot file (e.g. Output/config-snapshot.yaml written by collect_network_snapshot.sh) for the Network Settings tab (optional)")
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


        # Load threshold from config (default 0 = warn on any change)
        config_path_for_threshold = args.config or DEFAULT_CONFIG_PATH
        change_threshold: int = 0
        try:
            with open(config_path_for_threshold, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            change_threshold = int(_cfg.get("change_threshold", 0))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass


        # Derive approvals dir (sibling of report_dir's parent, matching serve_dashboard layout)
        _approvals_dir: Optional[str] = None
        _this_server_id: str = ""
        try:
            _this_server_id = server_id  # type: ignore[assignment]
        except NameError:
            pass
        if args.report:
            # Single-report mode: try to derive from config
            try:
                _cfg2_path = args.config or DEFAULT_CONFIG_PATH
                with open(_cfg2_path, "r", encoding="utf-8") as _f2:
                    _cfg2 = json.load(_f2)
                _rdir = _cfg2.get("report_dir", "")
                if _rdir:
                    _approvals_dir = os.path.join(
                        os.path.dirname(os.path.abspath(_rdir)), "approvals"
                    )
                _this_server_id = _cfg2.get("server_id", "")
            except Exception:  # noqa: BLE001
                pass
        elif report_dir:  # type: ignore[possibly-undefined]
            _approvals_dir = os.path.join(
                os.path.dirname(os.path.abspath(report_dir)), "approvals"  # type: ignore[arg-type]
            )








            report_paths = gather_report_paths(report_dir, server_id, args.history)
            if not report_paths:
                raise VisualizeError(
                    f"No report files found matching report_{server_id}_*.json in {report_dir}"
                )








        entries = []
        for path in report_paths:
            report = load_report_file(path)
            entries.append({"file": path, "label": _report_label(path, report), "data": report})








        # Application Snapshots tab (optional): scan a /bin-style directory.
        app_data: Dict[str, Any] = {}
        if args.app_dir:
            app_data = analyze_configured_paths(config_path)








        # Network Settings tab (optional): parse collect_network_snapshot.sh's YAML output.
        network_data: Dict[str, Any] = {}
        if args.network_snapshot:
            if not os.path.isfile(args.network_snapshot):
                raise VisualizeError(f"Network snapshot file not found: {args.network_snapshot}")
            yaml_data = load_yaml_snapshot(args.network_snapshot)
            network_data = parse_network_settings(yaml_data)








        server_id_for_title = entries[-1]["data"].get("server_id", "unknown")
        title = args.title or f"Server Snapshot Dashboard - {server_id_for_title}"








        threshold_data = _compute_threshold_data(
            entries, change_threshold, _approvals_dir, _this_server_id
        )
        html_out = build_dashboard_html(entries, title, app_data, network_data, threshold_data)


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

