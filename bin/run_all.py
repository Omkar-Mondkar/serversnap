#!/usr/bin/env python3
"""
Master Dashboard Generator (Python version)




Runs all steps in sequence:
1. Collect server configuration snapshots
2. Collect network settings
3. Generate comprehensive dashboard
4. Optionally serve on HTTP




Usage:
    python3 run_all.py --config /path/to/config.json
    python3 run_all.py --config config.json --app-dir /bin --serve --port 8080
    python3 run_all.py  # Uses defaults
"""




import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime




# Import change management modules
try:
    from baseline_manager import BaselineManager
    from change_approver import ChangeApprover
    HAS_APPROVAL_SYSTEM = True
except ImportError:
    HAS_APPROVAL_SYSTEM = False




# Colors
class Color:
    HEADER = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'








def print_header(msg):
    """Print section header"""
    print(f"\n{Color.HEADER}{'═' * 70}")
    print(f"{msg}")
    print(f"{'═' * 70}{Color.ENDC}\n")








def print_success(msg):
    """Print success message"""
    print(f"{Color.OKGREEN}✓ {msg}{Color.ENDC}")








def print_error(msg):
    """Print error message"""
    print(f"{Color.FAIL}✗ {msg}{Color.ENDC}")








def print_info(msg):
    """Print info message"""
    print(f"{Color.WARNING}➜ {msg}{Color.ENDC}")








def run_command(cmd, description=""):
    """Run shell command and return output"""
    if description:
        print_info(description)
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print_error(f"Command timed out: {cmd}")
        return 1, "", "Command timed out"
    except Exception as e:
        print_error(f"Command failed: {e}")
        return 1, "", str(e)


def main():
    parser = argparse.ArgumentParser(
        description="Master Dashboard Generator - Collects snapshots and generates dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_all.py --config /else/serversnap/config/config.json
  python3 run_all.py --config config.json --app-dir /bin --serve --port 8080
  python3 run_all.py  # Uses defaults
        """
    )
   
    parser.add_argument("--config", default="/else/serversnap/config/config.json",
                        help="Path to config.json (default: /else/serversnap/config/config.json)")
    parser.add_argument("--app-dir", default="/bin",
                        help="Application directory to scan (default: /bin)")
    parser.add_argument("--serve", action="store_true",
                        help="Start HTTP dashboard server")
    parser.add_argument("--host", default=None,
                        help="HTTP server bind address (default: from config.json dashboard.host, else 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None,
                        help="HTTP server port (default: from config.json dashboard.port, else 8080)")
    parser.add_argument("--no-network", action="store_true",
                        help="Skip network settings collection")
   
    args = parser.parse_args()
   
    # Get script directory
    script_dir = Path(__file__).parent.absolute()
    project_root = script_dir.parent
    config_file = Path(args.config).expanduser().absolute()
    app_dir = args.app_dir
    serve_dashboard = args.serve
    serve_host = args.host
    serve_port = args.port
    skip_network = args.no_network
   
    print_header("🚀 Master Dashboard Generator")
   
    # ========================================================================
    # STEP 1: Validate environment
    # ========================================================================
   
    print_header("STEP 1: Validating Environment")
   
    # Check Python
    print_info(f"Python version: {sys.version.split()[0]}")
    print_success("Python 3 ready")
   
    # Check config file
    if not config_file.exists():
        print_error(f"Config file not found: {config_file}")
        print_info("Usage: python3 run_all.py --config /path/to/config.json")
        return 2
    print_success(f"Config found: {config_file}")
   
    # Load config to get server_id and report_dir
    try:
        with open(config_file) as f:
            config = json.load(f)
        server_id = config.get("server_id", "unknown")
        report_dir = config.get("report_dir", str(project_root / "reports"))
        print_success(f"Server ID: {server_id}")
    except Exception as e:
        print_error(f"Failed to parse config: {e}")
        return 2
   
    # ========================================================================
    # STEP 1.5: Central Platform Pre-flight Check
    # ========================================================================


    print_header("STEP 1.5: Central Platform Pre-flight Check")


    _plat      = config.get("platform") or {}
    _plat_url  = _plat.get("url", "")
    _plat_key  = _plat.get("api_key", "")


    if not _plat_url:
        print_info("platform.url not set in config — Central Platform integration disabled.")
        print_info("  To enable: add a 'platform' block with 'url' and 'api_key' to config.json")
    else:
        # Derive base URL from ingest URL.
        _base = _plat_url.rstrip("/")
        if _base.endswith("/api/ingest"):
            _base = _base[: -len("/api/ingest")]


        print_info(f"Central URL : {_plat_url}")
        print_info(f"API key     : {_plat_key[:8]}... ({len(_plat_key)} chars)" if _plat_key else "API key     : (empty — auth will fail!)")


        # Check connectivity & auth by polling the pending-config endpoint.
        _ping_url = f"{_base}/api/server/{server_id}/pending-config"
        try:
            _ping_req = urllib.request.Request(
                _ping_url,
                headers={"X-API-Key": _plat_key},
                method="GET",
            )
            with urllib.request.urlopen(_ping_req, timeout=8) as _pr:
                _ping_body = json.loads(_pr.read().decode("utf-8"))
            if _ping_body.get("pending"):
                print_success(f"Central reachable — pending config queued (will apply in STEP 2)")
            else:
                print_success("Central reachable — no pending config queued")
        except urllib.error.HTTPError as _hpe:
            if _hpe.code == 401:
                print_error(
                    f"Central reachable but API key rejected (HTTP 401). "
                    f"Check 'platform.api_key' in config.json matches "
                    f"'api_key' in platform_config.json on the central server."
                )
            elif _hpe.code == 404:
                print_error(
                    f"Central reachable but server '{server_id}' not found (HTTP 404). "
                    f"The agent must push at least one snapshot first."
                )
            else:
                print_error(f"Central returned HTTP {_hpe.code} {_hpe.reason} — {_ping_url}")
        except urllib.error.URLError as _upe:
            print_error(
                f"Cannot reach Central at {_base}: {_upe.reason}\n"
                f"  • Is serve_central.py running on the central server?\n"
                f"  • Is the URL/port correct in config.json platform.url?"
            )
        except Exception as _pfe:
            print_error(f"Pre-flight check failed: {_pfe}")


    # ========================================================================
    # STEP 2: Take server configuration snapshot
    # ========================================================================
   
    print_header("STEP 2: Collecting Server Configuration Snapshot")


   
    server_snapshot_py = script_dir / "server_snapshot.py"
    if not server_snapshot_py.exists():
        print_error(f"server_snapshot.py not found at {server_snapshot_py}")
        return 2
   
    rc, out, err = run_command(
        f"python3 {server_snapshot_py} --config {config_file} -v",
        f"Running server_snapshot.py..."
    )
   
    if rc != 0 and rc != 1:  # 0 = no changes, 1 = changes detected
        print_error(f"Failed to collect snapshot (exit code {rc})")
        if out and out.strip():
            print(f"--- stdout ---")
            print(out.strip())
        if err and err.strip():
            print(f"--- stderr ---")
            print(err.strip())
        if not out.strip() and not err.strip():
            print("(no output captured)")
        return 2
   
    # Show all output so WARNING messages (e.g. pending-config, missing paths) are visible
    if out:
        for line in out.strip().split('\n'):
            if line.strip():
                print(f"  {line}")
   
    print_success("Configuration snapshot collected")


   
    # ========================================================================
    # STEP 3: Collect network settings
    # ========================================================================
   
    network_snapshot_yaml = project_root / "Output" / "config-snapshot.yaml"
   
    if not skip_network:
        print_header("STEP 3: Collecting Network Settings")
       
        collect_script = script_dir / "collect_network_snapshot.sh"
        output_dir = project_root / "Output"
        if collect_script.exists():
            print_info("Running network snapshot collection...")
            rc, out, err = run_command(f"bash {collect_script} {output_dir}")
           
            if rc == 0 and network_snapshot_yaml.exists():
                print_success(f"Network snapshot collected: {network_snapshot_yaml}")
            else:
                print_info("Network collection skipped (may require root or missing tools)")
        else:
            print_info("Network collection script not found - skipping")
    else:
        print_header("STEP 3: Collecting Network Settings")
        print_info("Skipped (--no-network flag)")
   
    # ========================================================================
    # STEP 4: Generate comprehensive dashboard
    # ========================================================================
   
    print_header("STEP 4: Generating Comprehensive Dashboard")
   
    visualize_py = script_dir / "visualize_report.py"
    if not visualize_py.exists():
        print_error(f"visualize_report.py not found at {visualize_py}")
        return 2
 
    dashboard_cmd = f"python3 {visualize_py} --config {config_file} --app-dir {app_dir}"
   
    if network_snapshot_yaml.exists() and not skip_network:
        dashboard_cmd += f" --network-snapshot {network_snapshot_yaml}"
        print_info(f"Including network settings from: {network_snapshot_yaml}")
    else:
        print_info("Network snapshot not available - dashboard will show drift + app tabs only")
   
    print_info(f"Scanning app directory: {app_dir}")
    rc, out, err = run_command(dashboard_cmd, "Generating dashboard...")
   
    if rc != 0:
        print_error("Failed to generate dashboard")
        print(err)
        return 2
   
    # Show relevant output
    if out:
        for line in out.strip().split('\n'):
            if any(x in line for x in ['Dashboard', 'Stable', 'Reports', 'Application', 'Network']):
                print(f"  {line}")
   
    print_success("Dashboard generated successfully")
   
    # ========================================================================
    # STEP 4.5: Push Dashboard to Central Platform (if configured)
    # ========================================================================


    print_header("STEP 4.5: Pushing Dashboard to Central Platform")


    _platform = config.get("platform", {})
    _push_url = _platform.get("url", "") if _platform else ""
    _api_key  = _platform.get("api_key", "") if _platform else ""


    if not _push_url:
        print_info("Platform push not configured (no 'platform.url' in config) — skipping.")
    else:
        print_info(f"Pushing to: {_push_url}")


        # Locate the latest snapshot and report.
        _snap_dir   = config.get("snapshot_dir", str(project_root / "snapshots"))
        _report_dir = config.get("report_dir", str(project_root / "reports"))
        _snaps   = sorted(glob.glob(os.path.join(_snap_dir,   f"snapshot_{server_id}_*.json")))
        _reports = sorted(glob.glob(os.path.join(_report_dir, f"report_{server_id}_*.json")))


        if not _snaps or not _reports:
            print_error("Cannot push: no snapshot/report found yet. Run STEP 2 first.")
        else:
            try:
                with open(_snaps[-1],   "r", encoding="utf-8") as _sfh:
                    _latest_snap = json.load(_sfh)
                with open(_reports[-1], "r", encoding="utf-8") as _rfh:
                    _latest_rep  = json.load(_rfh)


                _summ      = _latest_rep.get("summary", {})
                _has_chg   = bool(_summ.get("added") or _summ.get("deleted") or _summ.get("modified"))


                # Assemble minimal payload (mirrors push_to_platform in server_snapshot.py).
                _payload: dict = {
                    "server_id":      config.get("server_id", server_id),
                    "hostname":       config.get("hostname", ""),
                    "snapshot_at":    _latest_snap.get("snapshot_at", ""),
                    "has_changes":    _has_chg,
                    "change_summary": {
                        "added":    _summ.get("added", 0),
                        "deleted":  _summ.get("deleted", 0),
                        "modified": _summ.get("modified", 0),
                    },
                    "diff": {
                        "added":    _latest_rep.get("added",    []),
                        "deleted":  _latest_rep.get("deleted",  []),
                        "modified": _latest_rep.get("modified", []),
                    },
                    "snapshot": _latest_snap,
                }


                # Baseline diff (cumulative vs oldest snapshot).
                _all_snaps = sorted(glob.glob(os.path.join(_snap_dir, f"snapshot_{server_id}_*.json")))
                if len(_all_snaps) >= 2:
                    try:
                        import sys as _sys
                        _sys.path.insert(0, str(script_dir))
                        from server_snapshot import compare_snapshots as _cmp
                        with open(_all_snaps[0], "r", encoding="utf-8") as _bfh:
                            _base_snap = json.load(_bfh)
                        _bd = _cmp(_base_snap, _latest_snap)
                        _payload["baseline_diff"] = {
                            "added":    _bd.get("added", []),
                            "deleted":  _bd.get("deleted", []),
                            "modified": [{"path": m.get("path"), "changes": {k: {} for k in (m.get("changes") or {})}} for m in _bd.get("modified", [])],
                        }
                        _payload["baseline_change_summary"] = {
                            "added":    len(_payload["baseline_diff"]["added"]),
                            "deleted":  len(_payload["baseline_diff"]["deleted"]),
                            "modified": len(_payload["baseline_diff"]["modified"]),
                        }
                        _payload["baseline_has_changes"] = bool(
                            _payload["baseline_diff"]["added"]
                            or _payload["baseline_diff"]["deleted"]
                            or _payload["baseline_diff"]["modified"]
                        )
                    except Exception as _be:
                        print_info(f"  (baseline diff skipped: {_be})")


                # Attach sanitised config.
                _sensitive = {"api_key", "secret_key", "users"}
                _payload["config"] = {k: v for k, v in config.items()
                                       if k not in _sensitive and not k.startswith("_comment")}


                # Attach latest dashboard HTML (if present).
                _dash_path = os.path.join(_report_dir, "dashboard", f"latest_dashboard_{server_id}.html")
                if os.path.isfile(_dash_path):
                    with open(_dash_path, "rb") as _dfh:
                        _payload["dashboard_html_b64"] = base64.b64encode(_dfh.read()).decode("ascii")


                _body  = json.dumps(_payload).encode("utf-8")
                _req   = urllib.request.Request(
                    _push_url,
                    data=_body,
                    headers={"Content-Type": "application/json", "X-API-Key": _api_key},
                    method="POST",
                )
                with urllib.request.urlopen(_req, timeout=15) as _resp:
                    _status = _resp.status
                    if 200 <= _status < 300:
                        print_success(f"Dashboard push complete (HTTP {_status})")
                    else:
                        print_error(f"Push returned unexpected status {_status}")


            except urllib.error.HTTPError as _he:
                print_error(f"Push failed — HTTP {_he.code} {_he.reason}")
                print_info(f"  URL: {_push_url}")
                print_info("  Check that your platform api_key matches the central server's api_key.")
            except urllib.error.URLError as _ue:
                print_error(f"Push failed — could not reach central server: {_ue.reason}")
                print_info(f"  URL: {_push_url}")
                print_info("  Is serve_central.py running? Is the port correct?")
            except Exception as _pe:
                print_error(f"Push failed — unexpected error: {_pe}")


    # ========================================================================
    # STEP 5: Check for Changes and Update Approval Status
    # ========================================================================
   
    if HAS_APPROVAL_SYSTEM:
        print_header("STEP 5.5: Checking for Changes & Approval Status")
       
        try:
            baseline_mgr = BaselineManager(server_id, str(project_root / "baselines"))
            approver = ChangeApprover(server_id, str(project_root / "approvals"))
           
            # Initialize baselines if they don't exist
            baselines = baseline_mgr.get_all_baselines()
            if not baselines:
                print_info("No baselines found - initializing with current snapshots...")
                baseline_mgr.initialize_all_baselines({
                    "drift": {"initialized": True},
                    "app": {"initialized": True},
                    "network": {"initialized": True}
                })
                print_success("Initial baselines created (approved)")
            else:
                # Check for changes
                changes_detected = False
                pending_approvals = approver.get_pending_changes()
               
                for category in ["drift", "app", "network"]:
                    baseline = baseline_mgr.load_baseline(category)
                    has_changes, diff = baseline_mgr.compare_with_baseline(
                        category,
                        {"current": datetime.now().isoformat()}
                    )
                   
                    if has_changes and baseline:
                        changes_detected = True
                        approver.record_pending_changes(category, diff, datetime.now().isoformat())
                        print_info(f"⏳ Changes detected in {category} - pending approval")
               
                if changes_detected:
                    print_info("\n📋 PENDING APPROVALS:")
                    for cat, data in approver.get_pending_changes().items():
                        changes_count = len(data.get("changes", {})) if isinstance(data.get("changes"), dict) else 1
                        print_info(f"   {cat}: {changes_count} change(s) pending approval")
                    print_info("\n   Review and approve/reject changes in the dashboard!")
                else:
                    print_success("No changes detected - all baselines current")
           
            # Show summary
            summary = baseline_mgr.get_baseline_status_summary()
            print_info(f"\n📊 Baseline Status:")
            for cat, status_info in summary["baselines"].items():
                if status_info["status"] == "exists":
                    print_info(f"   {cat}: ✅ {status_info.get('reason', 'N/A')}")
                else:
                    print_info(f"   {cat}: ⚪ Not created")
       
        except Exception as e:
            print_info(f"Change detection skipped: {str(e)}")
    else:
        print_header("STEP 5.5: Change Detection")
        print_info("Approval system not available (optional)")
   
    print_success("Dashboard generated successfully")
    # ========================================================================
    # STEP 5: Display dashboard info
    # ========================================================================
   
    print_header("STEP 5: Dashboard Ready")
   
    dashboard_dir = Path(report_dir) / "dashboard"
    latest_dashboard = dashboard_dir / f"latest_dashboard_{server_id}.html"
   
    if latest_dashboard.exists():
        print_success(f"Dashboard: {latest_dashboard}")
        print(f"\n📊 Dashboard Components:")
        print(f"   1. Configuration Drift - File/directory changes")
        print(f"   2. Application Snapshots - Binary inventory from {app_dir}")
        if network_snapshot_yaml.exists():
            print(f"   3. Network Settings - System network configuration")
    else:
        print_error(f"Dashboard not found at {latest_dashboard}")
   
    # ========================================================================
    # STEP 6: Serve dashboard (optional)
    # ========================================================================
   
    if serve_dashboard:
        print_header("STEP 6: Starting Dashboard Server")
       
        serve_py = script_dir / "serve_dashboard.py"
        if not serve_py.exists():
            print_error(f"serve_dashboard.py not found at {serve_py}")
        else:
            print_info(f"Starting HTTP server on port {serve_port}...")
            print(f"\n🌐 Dashboard URL: http://127.0.0.1:{serve_port}/\n")
           
            # Start server (blocking)
            try:
                cmd = [
                    "python3", str(serve_py),
                    "--config", str(config_file)
                ]
                if serve_host:
                    cmd.extend(["--host", str(serve_host)])
                if serve_port:
                    cmd.extend(["--port", str(serve_port)])
                subprocess.run(cmd)
            except KeyboardInterrupt:
                print_info("Server stopped")
    else:
        print_header("STEP 6: Dashboard Server")
        print_info("To serve dashboard over HTTP, run:")
        print(f"\n    python3 {script_dir / 'serve_dashboard.py'} --config {config_file} --port 8080\n")
        print_info("Then visit: http://127.0.0.1:8080/")
   
    # ========================================================================
    # Summary
    # ========================================================================
   
    print_header("✓ All Steps Complete!")
   
    print(f"""
📋 Summary:
   Configuration Snapshot: ✓ Collected
   Network Settings:       ✓ {'Collected' if network_snapshot_yaml.exists() else 'Skipped'}
   Dashboard:              ✓ Generated




📂 Files:
   Config:     {config_file}
   Dashboard:  {latest_dashboard}




🚀 Next Steps:
   1. Open the dashboard:
      firefox {latest_dashboard}




   2. Schedule automatic updates (every 15 minutes):
      */15 * * * * python3 {script_dir / 'run_all.py'} --config {config_file}




📚 Full Options:
   python3 run_all.py --help
""")
   
    return 0








if __name__ == "__main__":
    sys.exit(main())



