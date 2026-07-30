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




DEFAULT_CONFIG_PATH = "/else/server_snapshot/config/config.json"
SCRIPT_VERSION = "1.0.0"


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




def find_latest_snapshot(snapshot_dir: str, server_id: str) -> Optional[str]:
    pattern = os.path.join(snapshot_dir, f"snapshot_{server_id}_*.json")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None




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
    lines = [
        f"Server Snapshot Change Report - {report['server_id']}",
        "=" * 60,
        f"Server ID:         {report['server_id']}",
        f"Hostname:          {report['hostname']}",
        f"Generated At:      {_short_timestamp(report['generated_at'])}",
        f"Previous Snapshot: {report['previous_snapshot'] or '(none - baseline run)'}",
        f"Current Snapshot:  {report['current_snapshot']}",
        "",
        "SUMMARY",
        "-------",
        f"Added:     {report['summary']['added']}",
        f"Deleted:   {report['summary']['deleted']}",
        f"Modified:  {report['summary']['modified']}",
        f"Unchanged: {report['summary']['unchanged']}",
        "",
    ]


    if report["added"]:
        lines.append("ADDED PATHS")
        lines.append("-----------")
        for item in report["added"]:
            lines.append(f"  + [{item.get('type', '?')}] {item['path']}")
        lines.append("")


    if report["deleted"]:
        lines.append("DELETED PATHS")
        lines.append("-------------")
        for item in report["deleted"]:
            lines.append(f"  - [{item.get('type', '?')}] {item['path']}")
        lines.append("")


    if report["modified"]:
        lines.append("MODIFIED PATHS")
        lines.append("--------------")
        for item in report["modified"]:
            lines.append(f"  * {item['path']}")
            if item.get("changes"):
                for field, vals in item["changes"].items():
                    label = FIELD_LABELS.get(field, field)
                    old_v = _fmt_field_value(field, vals["old"])
                    new_v = _fmt_field_value(field, vals["new"])
                    lines.append(f"      {label}: {old_v} -> {new_v}")
            if item.get("content_note"):
                lines.append(f"      note: {item['content_note']}")
            if item.get("content_diff"):
                lines.append("      diff:")
                for dline in item["content_diff"]:
                    lines.append(f"        {dline.rstrip()}")
            lines.append("")


    return "\n".join(lines)


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


    log.info("=== server_snapshot run start (server_id=%s, config=%s) ===", config.server_id, args.config)


    try:
        os.makedirs(config.snapshot_dir, exist_ok=True)
        _secure_dir(config.snapshot_dir)
        os.makedirs(config.report_dir, exist_ok=True)
        _secure_dir(config.report_dir)
    except OSError as exc:
        log.error("Could not create snapshot/report directories: %s", exc)
        return 2


    previous_snapshot_path = find_latest_snapshot(config.snapshot_dir, config.server_id)
    previous_snapshot: Optional[Dict[str, Any]] = None
    if previous_snapshot_path:
        try:
            with open(previous_snapshot_path, "r", encoding="utf-8") as f:
                previous_snapshot = json.load(f)
            log.info("Loaded previous snapshot: %s", previous_snapshot_path)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load previous snapshot %s: %s", previous_snapshot_path, exc)
    else:
        log.info("No previous snapshot found; this run establishes the baseline.")


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


    diff = compare_snapshots(previous_snapshot, new_snapshot)
    report = build_report(new_snapshot, previous_snapshot_path, new_snapshot_path, diff)
    text_report = render_text_report(report)


    try:
        json_report_path, text_report_path = save_report(report, text_report, config.report_dir, config.server_id)
        log.info("Saved report: %s / %s", json_report_path, text_report_path)
    except OSError as exc:
        log.error("Could not save report: %s", exc)
        return 2


    prune_old_files(config.snapshot_dir, f"snapshot_{config.server_id}_*.json", config.retention_count)
    prune_old_files(config.report_dir, f"report_{config.server_id}_*.json", config.retention_count)
    prune_old_files(config.report_dir, f"report_{config.server_id}_*.txt", config.retention_count)


    has_changes = bool(report["summary"]["added"] or report["summary"]["deleted"] or report["summary"]["modified"])


    if has_changes:
        log.warning(
            "Changes detected: %d added, %d deleted, %d modified",
            report["summary"]["added"], report["summary"]["deleted"], report["summary"]["modified"],
        )
        if not args.no_alert:
            send_alerts(config, report, json_report_path, text_report_path)
    else:
        log.info("No changes detected.")


    log.info("=== server_snapshot run complete (exit=%d) ===", 1 if has_changes else 0)
    return 1 if has_changes else 0


if __name__ == "__main__":
    sys.exit(main())
