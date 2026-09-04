#!/usr/bin/env python3
"""
server_snapshot.py
===================


Stateless, idempotent filesystem configuration snapshot & drift-detection tool.








Designed to run as root (via cron or a systemd timer) on Linux servers that are
shared between multiple teams. It records the metadata (and optionally the
content) of a configured set of files/directories, compares the result against
the previous snapshot found on disk, and writes a human-readable + JSON change
report. Optionally triggers a local alert command and/or a webhook on change.








Key design goals:
  - Stdlib only, no external dependencies.
  - Stateless: the only "state" carried between runs is what is stored on disk
    under the configured snapshot directory. Re-running the script never
    depends on anything held in memory from a previous process.
  - Idempotent: running it twice in a row with no filesystem changes produces
    an identical new snapshot and a report with zero differences.
  - Safe to scale to many servers: everything server-specific lives in
    config.json (server_id, paths, alerting), so the script itself can be
    deployed unmodified (e.g. via Ansible) with only the config differing
    per host.








Exit codes:
  0 - success, no changes detected
  1 - success, changes detected (added/deleted/modified entries)
  2 - fatal error (bad config, could not write snapshot/report, etc.)








Usage:
  server_snapshot.py [--config /path/to/config.json] [--no-alert] [-v]








See the accompanying README.md and config/config.json for full details.
Deploy path expected by the script's default: /else/serversnap/config/config.json
"""








from __future__ import annotations








import argparse
import base64
import difflib
import fnmatch
import glob
import hashlib
import json
import logging
import logging.handlers
import os
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple








try:
    import pwd  # type: ignore
except ImportError:  # pragma: no cover - non-POSIX platform
    pwd = None  # type: ignore








try:
    import grp  # type: ignore
except ImportError:  # pragma: no cover - non-POSIX platform
    grp = None  # type: ignore


DEFAULT_CONFIG_PATH = "/else/serversnap/config/config.json"
SCRIPT_VERSION = "2.0.0"








log = logging.getLogger("server_snapshot")
















class ConfigError(Exception):
    """Raised for any problem loading or validating the configuration file."""








# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------








def setup_logging(log_file: Optional[str], verbose: bool) -> logging.Logger:
    logger = logging.getLogger("server_snapshot")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()








    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )








    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)








    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5
            )
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Could not set up log file %s: %s", log_file, exc)








    return logger








# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------








@dataclass
class Config:
    server_id: str
    hostname: Optional[str]
    paths: List[Dict[str, Any]]
    snapshot_dir: str
    report_dir: str
    log_file: Optional[str]
    alerting: Dict[str, Any]
    platform: Dict[str, Any]
    max_content_size_bytes: int
    retention_count: int
    config_path: str


def _warn_if_insecure_permissions(path: str) -> None:
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            log.warning(
                "Config file %s is group/world-writable (mode=%o); "
                "recommend 'chmod 600 %s'",
                path, mode, path,
            )
    except OSError:
        pass




def load_config(config_path: str) -> Config:
    if not os.path.isfile(config_path):
        raise ConfigError(f"Config file not found: {config_path}")








    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Failed to read/parse config file {config_path}: {exc}") from exc








    _warn_if_insecure_permissions(config_path)








    missing = [k for k in ("server_id", "paths", "snapshot_dir", "report_dir") if k not in raw]
    if missing:
        raise ConfigError(f"Missing required config key(s): {', '.join(missing)}")








    paths = raw["paths"]
    if not isinstance(paths, list) or not paths:
        raise ConfigError("'paths' must be a non-empty list")








    for entry in paths:
        if not isinstance(entry, dict) or "path" not in entry:
            raise ConfigError(f"Each entry in 'paths' needs a 'path' key: {entry!r}")
        if not os.path.isabs(entry["path"]):
            raise ConfigError(f"Paths must be absolute: {entry['path']!r}")








    if not os.path.isabs(raw["snapshot_dir"]):
        raise ConfigError("'snapshot_dir' must be an absolute path")
    if not os.path.isabs(raw["report_dir"]):
        raise ConfigError("'report_dir' must be an absolute path")








    return Config(
        server_id=str(raw["server_id"]),
        hostname=raw.get("hostname"),
        paths=paths,
        snapshot_dir=raw["snapshot_dir"],
        report_dir=raw["report_dir"],
        log_file=raw.get("log_file"),
        alerting=raw.get("alerting") or {},
        platform=raw.get("platform") or {},
        max_content_size_bytes=int(raw.get("max_content_size_bytes", 5 * 1024 * 1024)),
        retention_count=int(raw.get("retention_count", 30)),
        config_path=config_path,
    )








# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------








def _uid_to_name(uid: int) -> Optional[str]:
    if pwd is None:
        return None
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return None


def _gid_to_name(gid: int) -> Optional[str]:
    if grp is None:
        return None
    try:
        return grp.getgrgid(gid).gr_name
    except (KeyError, OverflowError):
        return None
















def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()








def _resolve_include_content(path: str, default_include: bool, exceptions: List[Dict[str, Any]]) -> bool:
    """Apply per-path exceptions (exact match or glob pattern) on top of a
    directory/file's default include_content setting."""
    for exc in exceptions:
        pattern = exc.get("path") or exc.get("pattern")
        if not pattern:
            continue
        if pattern == path or fnmatch.fnmatch(path, pattern):
            if "include_content" in exc:
                return bool(exc["include_content"])
    return bool(default_include)








def iter_monitored_paths(entry_cfg: Dict[str, Any]):
    """Yield (absolute_path, include_content) tuples for a single config entry.








    Directories are expanded (recursively by default) into every contained
    file/directory/symlink. Symlinked directories are recorded as symlink
    entries but never followed, to avoid escaping the intended scope or
    infinite loops.
    """
    base_path = entry_cfg["path"]
    recursive = entry_cfg.get("recursive", True)
    default_include = bool(entry_cfg.get("include_content", False))
    exceptions = entry_cfg.get("exceptions") or []








    if not os.path.lexists(base_path):
        log.warning("Configured path does not exist on disk: %s", base_path)
        yield base_path, _resolve_include_content(base_path, default_include, exceptions)
        return








    st = os.lstat(base_path)








    if stat.S_ISLNK(st.st_mode):
        yield base_path, _resolve_include_content(base_path, default_include, exceptions)
        return








    if not stat.S_ISDIR(st.st_mode):
        # Plain file (or other special file type)
        yield base_path, _resolve_include_content(base_path, default_include, exceptions)
        return








    # Directory: always record the directory itself first.
    yield base_path, _resolve_include_content(base_path, default_include, exceptions)








    if not recursive:
        try:
            for name in sorted(os.listdir(base_path)):
                full = os.path.join(base_path, name)
                yield full, _resolve_include_content(full, default_include, exceptions)
        except OSError as exc:
            log.error("Could not list directory %s: %s", base_path, exc)
        return


    for root, dirs, files in os.walk(base_path, followlinks=False):
        dirs.sort()
        files.sort()
        for name in dirs:
            full = os.path.join(root, name)
            yield full, _resolve_include_content(full, default_include, exceptions)
        for name in files:
            full = os.path.join(root, name)
            yield full, _resolve_include_content(full, default_include, exceptions)
















def _hash_and_maybe_read(path: str, read_content: bool, max_size: int) -> Tuple[str, Optional[bytes]]:
    """Stream the file once, always computing its SHA256, and optionally
    capturing its content in memory as long as it stays within max_size."""
    h = hashlib.sha256()
    buf: Optional[bytearray] = bytearray() if read_content else None
    within_limit = True








    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
            if buf is not None and within_limit:
                if len(buf) + len(chunk) <= max_size:
                    buf.extend(chunk)
                else:
                    within_limit = False








    if buf is not None and within_limit:
        return h.hexdigest(), bytes(buf)
    return h.hexdigest(), None








def build_entry(path: str, include_content: bool, config: Config) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"path": path, "include_content": include_content}








    try:
        st = os.lstat(path)
    except OSError as exc:
        entry.update(exists=False, type="missing", error=str(exc))
        return entry








    entry["exists"] = True
    mode = st.st_mode








    if stat.S_ISLNK(mode):
        entry["type"] = "symlink"
        try:
            entry["symlink_target"] = os.readlink(path)
        except OSError as exc:
            entry["symlink_target"] = None
            entry["error"] = str(exc)
    elif stat.S_ISDIR(mode):
        entry["type"] = "directory"
    elif stat.S_ISREG(mode):
        entry["type"] = "file"
    else:
        entry["type"] = "other"








    entry["mode"] = oct(stat.S_IMODE(mode))
    entry["uid"] = st.st_uid
    entry["gid"] = st.st_gid
    entry["owner"] = _uid_to_name(st.st_uid)
    entry["group"] = _gid_to_name(st.st_gid)
    entry["size"] = st.st_size
    entry["mtime"] = _fmt_time(st.st_mtime)
    entry["ctime"] = _fmt_time(st.st_ctime)
    entry["sha256"] = None
    entry["content"] = None
    entry["content_encoding"] = None
    entry["content_truncated"] = False


    if entry["type"] == "file":
        try:
            sha256, content_bytes = _hash_and_maybe_read(
                path, read_content=include_content, max_size=config.max_content_size_bytes
            )
            entry["sha256"] = sha256
            if include_content:
                if content_bytes is None:
                    entry["content_truncated"] = True
                    log.warning(
                        "File %s exceeds max_content_size_bytes (%d); "
                        "content omitted from snapshot (hash still recorded)",
                        path, config.max_content_size_bytes,
                    )
                else:
                    try:
                        entry["content"] = content_bytes.decode("utf-8")
                        entry["content_encoding"] = "utf-8"
                    except UnicodeDecodeError:
                        entry["content"] = base64.b64encode(content_bytes).decode("ascii")
                        entry["content_encoding"] = "base64"
        except OSError as exc:
            entry["error"] = str(exc)
            log.warning("Could not read/hash %s: %s", path, exc)








    return entry




# ---------------------------------------------------------------------------
# Snapshot building / storage
# ---------------------------------------------------------------------------








def build_snapshot(config: Config) -> Dict[str, Any]:
    entries: Dict[str, Any] = {}








    for path_cfg in config.paths:
        try:
            for path, include_content in iter_monitored_paths(path_cfg):
                if path in entries:
                    continue  # de-duplicate overlapping config entries
                entries[path] = build_entry(path, include_content, config)
        except OSError as exc:
            log.error("Error processing configured path %s: %s", path_cfg.get("path"), exc)








    return {
        "schema_version": 1,
        "server_id": config.server_id,
        "hostname": config.hostname or socket.gethostname(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_path": config.config_path,
        "entry_count": len(entries),
        "entries": entries,
    }








def _atomic_write(path: str, content: str, mode: int = 0o600) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
















def _secure_dir(path: str) -> None:
    """Snapshot/report directories may contain full file contents (which can
    include secrets), so lock them down to root-only access."""
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        log.warning("Could not set permissions on directory %s: %s", path, exc)


def list_snapshots(snapshot_dir: str, server_id: str) -> List[str]:
    """Return all timestamped snapshot files for server_id, oldest first."""
    pattern = os.path.join(snapshot_dir, f"snapshot_{server_id}_*.json")
    return sorted(glob.glob(pattern))
















def resolve_snapshot_ref(ref: str, snapshot_dir: str, server_id: str) -> str:
    """Turn a user-supplied snapshot reference into a concrete file path.








    Accepts:
      - an absolute path to a snapshot JSON file
      - a bare filename, resolved relative to snapshot_dir
      - the keyword 'latest', resolved to latest_<server_id>.json
    """
    if ref == "latest":
        return os.path.join(snapshot_dir, f"latest_{server_id}.json")
    if os.path.isabs(ref):
        return ref
    return os.path.join(snapshot_dir, ref)




def load_snapshot_file(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise ConfigError(f"Snapshot file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Failed to read/parse snapshot file {path}: {exc}") from exc
















def _timestamp() -> str:
    """Return the current UTC time formatted as YYYY_MM_DD_HH_MM_SS, used for
    every snapshot/report filename so they sort chronologically and stay
    human-readable."""
    return datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S")
















def save_snapshot(snapshot: Dict[str, Any], snapshot_dir: str) -> str:
    os.makedirs(snapshot_dir, exist_ok=True)
    _secure_dir(snapshot_dir)








    ts = _timestamp()
    filename = f"snapshot_{snapshot['server_id']}_{ts}.json"
    path = os.path.join(snapshot_dir, filename)








    payload = json.dumps(snapshot, indent=2, sort_keys=True)
    _atomic_write(path, payload)
    _atomic_write(os.path.join(snapshot_dir, f"latest_{snapshot['server_id']}.json"), payload)








    return path








# ---------------------------------------------------------------------------
# Comparison / reporting
# ---------------------------------------------------------------------------








COMPARE_FIELDS = [
    "exists", "type", "mode", "uid", "gid", "owner", "group",
    "size", "mtime", "ctime", "sha256", "symlink_target",
]
# Human-readable labels used when rendering the text report.
FIELD_LABELS = {
    "exists": "existence",
    "type": "type",
    "mode": "permissions",
    "uid": "owner uid",
    "gid": "group gid",
    "owner": "owner name",
    "group": "group name",
    "size": "size (bytes)",
    "mtime": "last modified (mtime)",
    "ctime": "last status change (ctime)",
    "sha256": "content hash (sha256)",
    "symlink_target": "symlink target",
}
















def compare_snapshots(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    old_entries = old["entries"] if old else {}
    new_entries = new["entries"]








    old_paths = set(old_entries.keys())
    new_paths = set(new_entries.keys())








    added = sorted(new_paths - old_paths)
    deleted = sorted(old_paths - new_paths)
    common = sorted(new_paths & old_paths)








    modified = []
    unchanged_count = 0








    for path in common:
        o, n = old_entries[path], new_entries[path]
        changes = {}
        for field_name in COMPARE_FIELDS:
            ov, nv = o.get(field_name), n.get(field_name)
            if ov != nv:
                changes[field_name] = {"old": ov, "new": nv}








        content_diff = None
        content_note = None
        content_changed = "sha256" in changes








        if content_changed:
            if o.get("include_content") and n.get("include_content"):
                o_content, n_content = o.get("content"), n.get("content")
                if o_content is not None and n_content is not None:
                    content_diff = list(difflib.unified_diff(
                        o_content.splitlines(keepends=True),
                        n_content.splitlines(keepends=True),
                        fromfile=f"a{path}",
                        tofile=f"b{path}",
                    ))
                elif o.get("content_truncated") or n.get("content_truncated"):
                    content_note = (
                        "content changed (sha256 differs), but a line-by-line diff is not "
                        "available because the file exceeds max_content_size_bytes and its "
                        "content was truncated from the snapshot"
                    )
                else:
                    content_note = "content changed (sha256 differs); no stored content to diff"
            else:
                content_note = (
                    "content changed (sha256 differs); set include_content=true for this "
                    "path in config.json to capture a full line-by-line diff next run"
                )


        if changes or content_diff:
            modified.append({
                "path": path,
                "changes": changes,
                "content_diff": content_diff,
                "content_note": content_note,
            })
        else:
            unchanged_count += 1








    return {
        "added": [{"path": p, "type": new_entries[p].get("type")} for p in added],
        "deleted": [{"path": p, "type": old_entries[p].get("type")} for p in deleted],
        "modified": modified,
        "unchanged_count": unchanged_count,
    }








def build_report(
    new_snapshot: Dict[str, Any],
    previous_snapshot_path: Optional[str],
    new_snapshot_path: str,
    diff: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "server_id": new_snapshot["server_id"],
        "hostname": new_snapshot["hostname"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous_snapshot": previous_snapshot_path,
        "current_snapshot": new_snapshot_path,
        "summary": {
            "added": len(diff["added"]),
            "deleted": len(diff["deleted"]),
            "modified": len(diff["modified"]),
            "unchanged": diff["unchanged_count"],
        },
        "added": diff["added"],
        "deleted": diff["deleted"],
        "modified": diff["modified"],
    }
















def _short_timestamp(value: Any) -> str:
    """Render an ISO-8601 UTC timestamp as 'YYYY-MM-DD HH:MM:SS UTC' for the
    text report (full precision is still kept in the JSON report)."""
    if not isinstance(value, str):
        return "(none)" if value is None else str(value)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
















def _short_hash(value: Any) -> str:
    """Shorten a 64-char SHA256 hex digest to 'first12...last8' for the text
    report table (full hash is still kept in the JSON report)."""
    if not isinstance(value, str) or len(value) != 64:
        return "(none)" if value is None else str(value)
    return f"{value[:12]}...{value[-8:]}"
















def _fmt_field_value(field_name: str, value: Any) -> str:
    if field_name in ("mtime", "ctime"):
        return _short_timestamp(value)
    if field_name == "sha256":
        return _short_hash(value)
    if value is None:
        return "(none)"
    return str(value)




def render_text_report(report: Dict[str, Any]) -> str:
    divider = "=" * 78
    subdivider = "-" * 78
    lines = []
    lines.append(divider)
    lines.append("SERVER SNAPSHOT CHANGE REPORT")
    lines.append(divider)
    lines.append(f"Server            : {report['server_id']} ({report['hostname']})")
    lines.append(f"Generated         : {_short_timestamp(report['generated_at'])}")
    lines.append(f"Previous snapshot : {report['previous_snapshot'] or '(none - baseline run)'}")
    lines.append(f"Current snapshot  : {report['current_snapshot']}")
    lines.append("")
    s = report["summary"]
    lines.append(
        f"SUMMARY: {s['added']} added  |  {s['deleted']} deleted  |  "
        f"{s['modified']} modified  |  {s['unchanged']} unchanged"
    )
    lines.append(divider)




    if report["added"]:
        lines.append(f"\nADDED ({len(report['added'])})")
        lines.append(subdivider)
        for item in report["added"]:
            lines.append(f"  + [{item['type']}] {item['path']}")




    if report["deleted"]:
        lines.append(f"\nDELETED ({len(report['deleted'])})")
        lines.append(subdivider)
        for item in report["deleted"]:
            lines.append(f"  - [{item['type']}] {item['path']}")




    if report["modified"]:
        lines.append(f"\nMODIFIED ({len(report['modified'])})")
        lines.append(subdivider)
        for idx, item in enumerate(report["modified"], start=1):
            lines.append(f"[{idx}] {item['path']}")
            lines.append("")




            changes = item["changes"]
            if changes:
                label_w = max(len(FIELD_LABELS.get(f, f)) for f in changes) + 2
                old_w = max(
                    (len(_fmt_field_value(f, v["old"])) for f, v in changes.items()),
                    default=3,
                )
                old_w = max(old_w, 3) + 2
                lines.append(f"    {'Field'.ljust(label_w)}{'Old'.ljust(old_w)}New")
                lines.append(f"    {'-' * (label_w + old_w + 20)}")
                for field_name, vals in changes.items():
                    label = FIELD_LABELS.get(field_name, field_name)
                    old_disp = _fmt_field_value(field_name, vals["old"])
                    new_disp = _fmt_field_value(field_name, vals["new"])
                    lines.append(f"    {label.ljust(label_w)}{old_disp.ljust(old_w)}{new_disp}")




                if "size" in changes and isinstance(changes["size"]["old"], int) and isinstance(
                    changes["size"]["new"], int
                ):
                    delta = changes["size"]["new"] - changes["size"]["old"]
                    sign = "+" if delta >= 0 else ""
                    lines.append(f"\n    Size changed by {sign}{delta} bytes.")




            if item.get("content_note"):
                lines.append(f"\n    Note: {item['content_note']}")




            if item["content_diff"]:
                lines.append("\n    Content diff (old vs. new):")
                for dl in item["content_diff"]:
                    lines.append("        " + dl.rstrip("\n"))




            lines.append("")
            lines.append(subdivider)




    if not (report["added"] or report["deleted"] or report["modified"]):
        lines.append("\nNo changes detected.")




    return "\n".join(lines) + "\n"


def save_report(
    report: Dict[str, Any], text_report: str, report_dir: str, server_id: str
) -> Tuple[str, str]:
    os.makedirs(report_dir, exist_ok=True)
    _secure_dir(report_dir)








    ts = _timestamp()
    json_path = os.path.join(report_dir, f"report_{server_id}_{ts}.json")
    text_path = os.path.join(report_dir, f"report_{server_id}_{ts}.txt")



    payload = json.dumps(report, indent=2, sort_keys=True)
    _atomic_write(json_path, payload)
    _atomic_write(text_path, text_report)








    _atomic_write(os.path.join(report_dir, f"latest_report_{server_id}.json"), payload)
    _atomic_write(os.path.join(report_dir, f"latest_report_{server_id}.txt"), text_report)








    return json_path, text_path








def save_manual_compare_report(
    report: Dict[str, Any], text_report: str, report_dir: str, server_id: str
) -> Tuple[str, str]:
    """Save an ad hoc --compare report under a 'compare_' prefix so it never
    collides with, or gets pruned alongside, the regular scheduled reports."""
    os.makedirs(report_dir, exist_ok=True)
    _secure_dir(report_dir)








    ts = _timestamp()
    json_path = os.path.join(report_dir, f"compare_{server_id}_{ts}.json")
    text_path = os.path.join(report_dir, f"compare_{server_id}_{ts}.txt")








    _atomic_write(json_path, json.dumps(report, indent=2, sort_keys=True))
    _atomic_write(text_path, text_report)








    return json_path, text_path
















def prune_old_files(directory: str, pattern: str, keep: int) -> None:
    if keep is None or keep <= 0:
        return
    files = sorted(glob.glob(os.path.join(directory, pattern)))
    excess = len(files) - keep
    for f in files[:max(0, excess)]:
        try:
            os.remove(f)
        except OSError as exc:
            log.warning("Could not remove old file %s: %s", f, exc)








# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------








def send_alerts(config: Config, report: Dict[str, Any], json_report_path: str, text_report_path: str) -> None:
    command = config.alerting.get("command")
    webhook_url = config.alerting.get("webhook_url")








    if command:
        env = os.environ.copy()
        env["SERVER_SNAPSHOT_SERVER_ID"] = str(report["server_id"])
        env["SERVER_SNAPSHOT_ADDED"] = str(report["summary"]["added"])
        env["SERVER_SNAPSHOT_DELETED"] = str(report["summary"]["deleted"])
        env["SERVER_SNAPSHOT_MODIFIED"] = str(report["summary"]["modified"])
        env["SERVER_SNAPSHOT_REPORT_JSON"] = json_report_path
        env["SERVER_SNAPSHOT_REPORT_TEXT"] = text_report_path
        try:
            # Pass report paths as argv (never shell=True) - the alert
            # command/script is responsible for reading them itself.
            subprocess.run(
                [command, json_report_path, text_report_path],
                env=env,
                timeout=30,
                check=False,
                capture_output=True,
            )
            log.info("Alert command executed: %s", command)
        except (OSError, subprocess.SubprocessError) as exc:
            log.error("Alert command failed: %s", exc)








    if webhook_url:
        try:
            payload = json.dumps({
                "server_id": report["server_id"],
                "hostname": report["hostname"],
                "generated_at": report["generated_at"],
                "summary": report["summary"],
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - local/internal use only
                log.info("Webhook notified (%s), status=%s", webhook_url, resp.status)
        except (urllib.error.URLError, ValueError, OSError) as exc:
            log.error("Webhook call failed: %s", exc)








# ---------------------------------------------------------------------------
# Platform push
# ---------------------------------------------------------------------------








def _pull_pending_config(config: Config, config_path: str, central_base_url: str, api_key: str) -> bool:
    """Poll central for a pending config update; apply it if present.


    Steps:
      1. GET <central>/api/server/<id>/pending-config
      2. If pending=True, write the returned config to config_path (with backup).
      3. DELETE <central>/api/server/<id>/pending-config to acknowledge.


    Returns True if a pending config was applied, False otherwise.
    All errors are non-fatal and logged as warnings.
    """
    base = central_base_url.rstrip("/")
    # Derive the central base URL from the ingest URL (strip /api/ingest if present).
    if base.endswith("/api/ingest"):
        base = base[: -len("/api/ingest")]


    poll_url = f"{base}/api/server/{config.server_id}/pending-config"
    delete_url = f"{base}/api/server/{config.server_id}/pending-config"


    # Both pending-config endpoints are authenticated with the same API key
    # used by the ingest endpoint (X-API-Key header).
    headers: Dict[str, str] = {"X-API-Key": api_key}


    try:
        req = urllib.request.Request(poll_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        log.warning(
            "Pending-config poll failed — HTTP %s %s from %s. "
            "Check that serve_central.py is running, the URL is correct, "
            "and the api_key matches.",
            exc.code, exc.reason, poll_url,
        )
        return False
    except (urllib.error.URLError, OSError) as exc:
        log.warning(
            "Pending-config poll failed — could not reach central at %s: %s. "
            "Check 'platform.url' in config.json.",
            poll_url, exc,
        )
        return False
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("Pending-config poll: unexpected response from central: %s", exc)
        return False


    if not body.get("pending"):
        log.debug("No pending config from central.")
        return False


    new_cfg = body.get("config")
    if not isinstance(new_cfg, dict):
        log.warning("Pending config from central is not a dict — ignoring.")
        return False


    # Remove the internal _queued_at marker before writing.
    new_cfg.pop("_queued_at", None)
    new_cfg.pop("_source", None)


    # Backup existing config.
    from datetime import datetime as _dt  # already imported at top, re-reference
    ts = _dt.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = f"{config_path}.{ts}.bak"
    try:
        import shutil as _shutil
        if os.path.isfile(config_path):
            _shutil.copy2(config_path, backup_path)
    except OSError as exc:
        log.warning("Could not create config backup %s: %s — aborting pending config apply.", backup_path, exc)
        return False


    # Merge on top of the existing config.json rather than a full overwrite.
    # The central config editor UI only manages a subset of top-level keys
    # (server_id, hostname, snapshot_dir, report_dir, log_file,
    # max_content_size_bytes, retention_count, change_threshold, paths,
    # alerting, dashboard) — it has no field for "platform" or any
    # "_comment_*" keys. A full overwrite would silently drop those,
    # including platform.url/api_key, breaking future pushes to central.
    merged_cfg: Dict[str, Any] = {}
    try:
        with open(config_path, "r", encoding="utf-8") as _cfh:
            existing_raw = json.load(_cfh)
        if isinstance(existing_raw, dict):
            merged_cfg = existing_raw
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read existing config %s for merge: %s — using central config as-is.", config_path, exc)
    merged_cfg.update(new_cfg)


    # Atomic write.
    tmp = config_path + ".pending.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(merged_cfg, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, config_path)
    except OSError as exc:
        log.warning("Could not write pending config to %s: %s", config_path, exc)
        # Try to remove temp file.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


    log.info("Applied pending config from central (backup: %s).", backup_path)


    # Acknowledge: DELETE from central (also authenticated with API key).
    try:
        del_req = urllib.request.Request(delete_url, headers=headers, method="DELETE")
        with urllib.request.urlopen(del_req, timeout=10) as _resp:  # noqa: S310
            pass
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Could not acknowledge pending config deletion from central: %s", exc)
        # Non-fatal — config was already applied locally.


    return True




def _pull_pending_baseline(config: Config, central_base_url: str, api_key: str) -> bool:
    """Apply one baseline decision queued by the Central Platform."""
    base = central_base_url.rstrip("/")
    if base.endswith("/api/ingest"):
        base = base[: -len("/api/ingest")]
    decision_url = f"{base}/api/server/{config.server_id}/pending-baseline"
    headers = {"X-API-Key": api_key}
    try:
        request = urllib.request.Request(decision_url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Pending-baseline poll failed: %s", exc)
        return False


    if not payload.get("pending"):
        return False
    decision = payload.get("decision")
    if not isinstance(decision, dict) or decision.get("action") not in ("APPROVED", "REJECTED"):
        log.warning("Pending-baseline response is invalid; leaving it queued.")
        return False


    if decision["action"] == "APPROVED":
        snapshot = decision.get("snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("entries"), dict):
            log.warning("Approved baseline is missing snapshot data; leaving it queued.")
            return False
        baseline_dir = os.path.join(os.path.dirname(config.snapshot_dir), "baseline")
        try:
            os.makedirs(baseline_dir, exist_ok=True)
            _secure_dir(baseline_dir)
            baseline_path = os.path.join(baseline_dir, f"baseline_{config.server_id}.json")
            _atomic_write(baseline_path, json.dumps(snapshot, indent=2, sort_keys=True))
            log.info("Applied approved baseline from Central: %s", decision.get("snapshot_id"))
        except OSError as exc:
            log.warning("Could not write approved baseline: %s", exc)
            return False
    else:
        log.info("Recorded Central rejection for snapshot: %s", decision.get("snapshot_id"))


    try:
        request = urllib.request.Request(decision_url, headers=headers, method="DELETE")
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310
            pass
        return True
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Applied Central decision but could not acknowledge it: %s", exc)
        return False


def push_to_platform(
    config: Config,
    snapshot: Dict[str, Any],
    report: Dict[str, Any],
    has_changes: bool,
) -> bool:
    """POST snapshot + dashboard HTML to the central platform.


    Reads ``config.platform`` for connection details.  All errors are
    non-fatal: failures are logged as warnings and the main run continues.
    """
    platform = config.platform
    url = platform.get("url")
    if not url:
        # Platform push not configured — silently skip.
        return True


    api_key = platform.get("api_key", "")
    push_always = bool(platform.get("push_always", True))


    if not push_always and not has_changes:
        log.debug("Platform push skipped: push_always=false and no changes detected.")
        return True


    # Attempt to read the latest generated dashboard HTML and base64-encode it.
    # visualize_report.py writes the stable copy to:
    #   <report_dir>/dashboard/latest_dashboard_<server_id>.html
    # If the file does not exist yet (visualize_report hasn't run), we omit it.
    dashboard_html_b64: Optional[str] = None
    stable_html_path = os.path.join(
        config.report_dir, "dashboard", f"latest_dashboard_{config.server_id}.html"
    )
    if os.path.isfile(stable_html_path):
        try:
            with open(stable_html_path, "rb") as fh:
                dashboard_html_b64 = base64.b64encode(fh.read()).decode("ascii")
        except OSError as exc:
            log.warning("Platform push: could not read dashboard HTML %s: %s", stable_html_path, exc)
    else:
        log.debug(
            "Platform push: dashboard HTML not found at %s — omitting from payload.",
            stable_html_path,
        )


    summary = report.get("summary", {})
    payload_dict: Dict[str, Any] = {
        "server_id": config.server_id,
        "hostname": config.hostname or snapshot.get("hostname", ""),
        "snapshot_at": snapshot.get("snapshot_at", ""),
        "has_changes": has_changes,
        "change_summary": {
            "added": summary.get("added", 0),
            "deleted": summary.get("deleted", 0),
            "modified": summary.get("modified", 0),
        },
        "diff": {
            "added": report.get("added", []),
            "deleted": report.get("deleted", []),
            "modified": report.get("modified", []),
        },
        "snapshot": snapshot,
    }


    # -----------------------------------------------------------------------
    # Historical snapshots are not implicitly trusted. Only an explicitly
    # approved copy is eligible to be the baseline, even after retention.
    # -----------------------------------------------------------------------
    baseline_diff: Dict[str, Any] = {"added": [], "deleted": [], "modified": []}
    baseline_change_summary: Dict[str, int] = {"added": 0, "deleted": 0, "modified": 0}
    baseline_has_changes = False
    try:
        baseline_path = os.path.join(
            os.path.dirname(config.snapshot_dir), "baseline", f"baseline_{config.server_id}.json"
        )
        if os.path.isfile(baseline_path):
            with open(baseline_path, "r", encoding="utf-8") as _bfh:
                baseline_snapshot = json.load(_bfh)
            raw_bdiff = compare_snapshots(baseline_snapshot, snapshot)


            def _slim_modified(item: Dict[str, Any]) -> Dict[str, Any]:
                """Strip content_diff / content_note from modified items to keep payload small.
                Central only needs path + changed field names; full diffs are in the dashboard HTML."""
                return {
                    "path": item.get("path"),
                    "changes": {k: {} for k in (item.get("changes") or {})},
                }


            baseline_diff = {
                "added":    raw_bdiff.get("added", []),
                "deleted":  raw_bdiff.get("deleted", []),
                "modified": [_slim_modified(m) for m in raw_bdiff.get("modified", [])],
            }
            baseline_change_summary = {
                "added":    len(baseline_diff["added"]),
                "deleted":  len(baseline_diff["deleted"]),
                "modified": len(baseline_diff["modified"]),
            }
            baseline_has_changes = bool(
                baseline_diff["added"]
                or baseline_diff["deleted"]
                or baseline_diff["modified"]
            )
    except Exception as _exc:  # noqa: BLE001
        log.debug("Platform push: could not compute baseline diff: %s", _exc)


    payload_dict["baseline_diff"] = baseline_diff
    payload_dict["baseline_change_summary"] = baseline_change_summary
    payload_dict["baseline_has_changes"] = baseline_has_changes


    # Include the agent's sanitised config so the central platform can store
    # and serve it for the Config Editor UI.  Sensitive keys are removed.
    _SENSITIVE_CONFIG_KEYS = {"api_key", "secret_key", "users"}
    try:
        with open(config.config_path, "r", encoding="utf-8") as _fh:
            _raw_cfg = json.load(_fh)
        payload_dict["config"] = {
            k: v for k, v in _raw_cfg.items()
            if k not in _SENSITIVE_CONFIG_KEYS and not k.startswith("_comment")
        }
    except (OSError, json.JSONDecodeError) as _exc:
        log.debug("Could not include config in push payload: %s", _exc)


    if dashboard_html_b64 is not None:
        payload_dict["dashboard_html_b64"] = dashboard_html_b64


    try:
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
    except (TypeError, ValueError) as exc:
        log.warning("Platform push: failed to serialise payload: %s", exc)
        return False


    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            if 200 <= resp.status < 300:
                log.info("Platform push succeeded (%s), status=%s", url, resp.status)
                return True
            else:
                log.warning(
                    "Platform push returned non-2xx status %s from %s", resp.status, url
                )
                return False
    except urllib.error.HTTPError as exc:
        log.warning(
            "Platform push HTTP error %s from %s: %s", exc.code, url, exc.reason
        )
        return False
    except urllib.error.URLError as exc:
        log.warning("Platform push failed (unreachable %s): %s", url, exc.reason)
        return False
    except OSError as exc:
        log.warning("Platform push I/O error (%s): %s", url, exc)
        return False








# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------








def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Take and compare filesystem configuration snapshots.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--no-alert", action="store_true", help="Skip alerting even if changes are found")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--list-snapshots", action="store_true",
        help="List available snapshots for this server_id (newest last) and exit",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("OLD", "NEW"),
        help=(
            "Compare two existing snapshots instead of taking a new one. "
            "Each of OLD/NEW may be an absolute path to a snapshot JSON file, "
            "a bare filename located in snapshot_dir, or the keyword 'latest' "
            "for latest_<server_id>.json. Writes a compare_<server_id>_<ts> "
            "report and prints the text report to stdout; does not touch "
            "alerting or the regular snapshot/report retention."
        ),
    )
    parser.add_argument("--version", action="version", version=f"server_snapshot {SCRIPT_VERSION}")
    parser.add_argument(
        "--push-only",
        action="store_true",
        help="Skip snapshot collection and only push the latest data + dashboard to the Central Platform.",
    )
    args = parser.parse_args(argv)


    global log
    log = setup_logging(None, args.verbose)  # console-only until config is loaded


    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2








    log = setup_logging(config.log_file, args.verbose)








    if args.list_snapshots:
        snapshots = list_snapshots(config.snapshot_dir, config.server_id)
        if not snapshots:
            print(f"No snapshots found for server_id={config.server_id!r} in {config.snapshot_dir}")
            return 0
        for path in snapshots:
            print(path)
        return 0








    if args.compare:
        old_ref, new_ref = args.compare
        old_path = resolve_snapshot_ref(old_ref, config.snapshot_dir, config.server_id)
        new_path = resolve_snapshot_ref(new_ref, config.snapshot_dir, config.server_id)
        try:
            old_snapshot = load_snapshot_file(old_path)
            new_snapshot = load_snapshot_file(new_path)
        except ConfigError as exc:
            log.error("%s", exc)
            return 2








        diff = compare_snapshots(old_snapshot, new_snapshot)
        report = build_report(new_snapshot, old_path, new_path, diff)
        text_report = render_text_report(report)
        print(text_report)








        try:
            json_report_path, text_report_path = save_manual_compare_report(
                report, text_report, config.report_dir, config.server_id
            )
            log.info("Saved ad hoc compare report: %s / %s", json_report_path, text_report_path)
        except OSError as exc:
            log.error("Could not save compare report: %s", exc)
            return 2








        has_changes = bool(
            report["summary"]["added"] or report["summary"]["deleted"] or report["summary"]["modified"]
        )
        return 1 if has_changes else 0


    # Handle --push-only mode
    if args.push_only:
        log.info("Running in --push-only mode.")
        snapshot_paths = sorted(glob.glob(os.path.join(config.snapshot_dir, f"snapshot_{config.server_id}_*.json")))
        report_paths = sorted(glob.glob(os.path.join(config.report_dir, f"report_{config.server_id}_*.json")))
        if not snapshot_paths or not report_paths:
            log.error("Cannot push: no snapshots or reports found.")
            return 1
           
        try:
            with open(snapshot_paths[-1], "r", encoding="utf-8") as f:
                latest_snapshot = json.load(f)
            with open(report_paths[-1], "r", encoding="utf-8") as f:
                latest_report = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to read latest snapshot/report: %s", exc)
            return 1
           
        summary = latest_report.get("summary", {})
        has_changes = bool(summary.get("added") or summary.get("deleted") or summary.get("modified"))
        success = push_to_platform(config, latest_snapshot, latest_report, has_changes)
        if success:
            log.info("Push complete.")
            return 0
        else:
            log.error("Platform push failed.")
            return 1
    log.info("=== server_snapshot run start (server_id=%s, config=%s) ===", config.server_id, args.config)


    # -----------------------------------------------------------------------
    # Check for a pending config update queued by the central platform.
    # If found, apply it to config.json and reload, then acknowledge.
    # -----------------------------------------------------------------------
    platform = config.platform
    central_url = platform.get("url", "")
    if central_url:
        _applied = _pull_pending_config(config, args.config, central_url, platform.get("api_key", ""))
        if _applied:
            # Reload config so the rest of the run uses the updated values.
            try:
                config = load_config(args.config)
                log.info("Config reloaded after applying pending update from central.")
            except ConfigError as exc:
                log.error("Reloaded config is invalid after applying pending update: %s", exc)
                return 2


    if central_url:
        _pull_pending_baseline(config, central_url, config.platform.get("api_key", ""))








    try:
        os.makedirs(config.snapshot_dir, exist_ok=True)
        _secure_dir(config.snapshot_dir)
        os.makedirs(config.report_dir, exist_ok=True)
        _secure_dir(config.report_dir)
    except OSError as exc:
        log.error("Could not create snapshot/report directories: %s", exc)
        return 2

    baseline_path = os.path.join(
        os.path.dirname(config.snapshot_dir), "baseline", f"baseline_{config.server_id}.json"
    )
    previous_snapshot_path: Optional[str] = baseline_path if os.path.isfile(baseline_path) else None
    previous_snapshot: Optional[Dict[str, Any]] = None
    if previous_snapshot_path:
        try:
            with open(previous_snapshot_path, "r", encoding="utf-8") as f:
                previous_snapshot = json.load(f)
            log.info("Loaded approved baseline: %s", previous_snapshot_path)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load approved baseline %s: %s", previous_snapshot_path, exc)
    else:
        log.info("No approved baseline found; this initial snapshot will be auto-approved as the baseline.")

    try:
        new_snapshot = build_snapshot(config)
    except Exception as exc:  # noqa: BLE001 - top-level guard, must never crash unlogged
        log.exception("Fatal error while building snapshot: %s", exc)
        return 2

    try:
        new_snapshot_path = save_snapshot(new_snapshot, config.snapshot_dir)
        log.info("Saved new snapshot: %s (%d entries)", new_snapshot_path, new_snapshot["entry_count"])
    except OSError as exc:
        log.error("Could not save snapshot: %s", exc)
        return 2

    is_initial_baseline = previous_snapshot is None
    if is_initial_baseline:
        baseline_dir = os.path.dirname(baseline_path)
        try:
            os.makedirs(baseline_dir, exist_ok=True)
            _secure_dir(baseline_dir)
            from audit_store import AuditStore  # type: ignore
            audit_store = AuditStore(config.snapshot_dir, config.server_id)
            audit_store.promote(new_snapshot_path)
            audit_store.append("APPROVED", new_snapshot_path, "system (initial baseline)", "Auto-approved initial baseline")
            log.info("Auto-approved initial snapshot as baseline: %s", baseline_path)
        except Exception as exc:
            log.warning("Could not record initial baseline in audit store: %s", exc)
            try:
                _atomic_write(baseline_path, json.dumps(new_snapshot, indent=2, sort_keys=True))
                log.info("Saved initial baseline directly: %s", baseline_path)
            except OSError as b_exc:
                log.warning("Could not write baseline file: %s", b_exc)

    diff = compare_snapshots(previous_snapshot, new_snapshot)
    report = build_report(new_snapshot, previous_snapshot_path, new_snapshot_path, diff)
    text_report = render_text_report(report)

    try:
        json_report_path, text_report_path = save_report(report, text_report, config.report_dir, config.server_id)
        log.info("Saved report: %s / %s", json_report_path, text_report_path)
    except OSError as exc:
        log.error("Could not save report: %s", exc)
        return 2

    if is_initial_baseline:
        try:
            from report_approval_store import ReportApprovalStore  # type: ignore
            approvals_dir = os.path.join(os.path.dirname(config.snapshot_dir), "approvals")
            rep_store = ReportApprovalStore(config.server_id, approvals_dir)
            rep_basename = os.path.basename(json_report_path)
            rep_store.set_pending(rep_basename, rep_basename, len(diff["added"]), 0)
            rep_store.approve(rep_basename, "Auto-approved initial baseline")
        except Exception:
            pass
        try:
            from baseline_manager import BaselineManager  # type: ignore
            baselines_dir = os.path.join(os.path.dirname(config.snapshot_dir), "baselines")
            os.makedirs(baselines_dir, exist_ok=True)
            mgr = BaselineManager(config.server_id, baselines_dir)
            mgr.save_golden_snapshot(report, "Initial Baseline")
        except Exception:
            pass

    prune_old_files(config.snapshot_dir, f"snapshot_{config.server_id}_*.json", config.retention_count)
    prune_old_files(config.report_dir, f"report_{config.server_id}_*.json", config.retention_count)
    prune_old_files(config.report_dir, f"report_{config.server_id}_*.txt", config.retention_count)

    if is_initial_baseline:
        has_changes = False
        log.info("Initial snapshot auto-approved as baseline (%d entries).", new_snapshot["entry_count"])
    else:
        has_changes = bool(report["summary"]["added"] or report["summary"]["deleted"] or report["summary"]["modified"])

    if has_changes:
        log.warning(
            "Changes detected: %d added, %d deleted, %d modified",
            report["summary"]["added"], report["summary"]["deleted"], report["summary"]["modified"],
        )
        if not args.no_alert:
            send_alerts(config, report, json_report_path, text_report_path)
    elif not is_initial_baseline:
        log.info("No changes detected.")








    # Platform push runs independently of --no-alert and of whether changes
    # were detected (push_to_platform() enforces push_always internally).
    push_to_platform(config, new_snapshot, report, has_changes)








    log.info("=== server_snapshot run complete (exit=%d) ===", 1 if has_changes else 0)
    return 1 if has_changes else 0








if __name__ == "__main__":
    sys.exit(main())



