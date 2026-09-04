#!/usr/bin/env python3
"""
serve_central.py
================








Central hub for the ServerSnap multi-server platform.


Agents running server_snapshot.py POST their snapshots here; humans browse
the fleet dashboard at http://<central-host>:<port>/.








Design goals (matching server_snapshot.py / serve_dashboard.py):
  - Stdlib only, no external dependencies.
  - Long-running foreground process, supervised by cron (@reboot) or nohup.
  - Flat-file storage under central_data/<server_id>/ — no database.
  - Two-layer authentication:
      * Agents: X-API-Key header (constant-time compare).
      * Browsers: username+password -> HMAC-SHA256 signed session cookie.
  - Auto-discovery: first push from a new server_id creates its storage dir.
  - Config cascade: global platform_config.json defaults, per-server
    override.json supersedes (loaded fresh on each relevant request).








SECURITY WARNING — read before exposing beyond localhost:
  This server speaks plain HTTP with NO TLS. The API key and session cookie
  travel in the clear. In production, put a reverse proxy (nginx, Caddy)
  in front for TLS termination. The default bind address is 127.0.0.1.








Exit codes:
  0 - clean shutdown (SIGINT/SIGTERM)
  2 - fatal error (bad arguments, bind failure, config error)








Usage:
  serve_central.py --config /path/to/platform_config.json
  serve_central.py --config platform_config.json --host 0.0.0.0 --port 8090
  serve_central.py --hash-password mysecretpassword


"""








from __future__ import annotations








import argparse
import base64
import functools
import hashlib
import hmac
import http.server
import json
import os
import secrets
import signal
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional








SCRIPT_VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = "/else/serversnap/config/platform_config.json"


# Session cookie name used in Set-Cookie / Cookie headers.
SESSION_COOKIE_NAME = "sscentral_session"


# How many bytes to allow for the ingest body, max (64 MiB).
DEFAULT_MAX_INGEST_BYTES = 64 * 1024 * 1024


# Session TTL hours — how long a browser session stays valid.
SESSION_TTL_HOURS = 24


# Fields allowed in per-server override.json (POST /api/server/<id>/config).
ALLOWED_OVERRIDE_KEYS = {"stale_threshold_minutes", "history_retention_count"}


# Keys stripped from agent_config.json when returned via GET /api/server/<id>/config.
AGENT_CONFIG_SENSITIVE_KEYS = {"api_key", "secret_key", "users", "_comment", "_comment_general"}


# Keys beginning with this prefix are comment-only and always stripped.
AGENT_CONFIG_COMMENT_PREFIX = "_comment"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------








class CentralError(Exception):
    """Raised for any fatal problem starting the central server."""








# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------








def load_platform_config(config_path: str) -> Dict[str, Any]:
    """Load and minimally validate platform_config.json."""
    if not os.path.isfile(config_path):
        raise CentralError(f"Config file not found: {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CentralError(f"Failed to read/parse {config_path}: {exc}") from exc
    for key in ("api_key", "secret_key"):
        if not raw.get(key):
            raise CentralError(f"platform_config.json is missing required key: '{key}'")
    if not raw.get("users"):
        raise CentralError("platform_config.json must have at least one user in 'users'")
    return raw




def get_effective_config(global_cfg: Dict[str, Any], data_dir: str, server_id: str) -> Dict[str, Any]:
    """Merge global config with per-server override.json (override wins).


    Implements Task 4.3 / Design D7.
    """
    effective = dict(global_cfg)
    override_path = os.path.join(data_dir, server_id, "override.json")
    if os.path.isfile(override_path):
        try:
            with open(override_path, "r", encoding="utf-8") as fh:
                override = json.load(fh)
            effective.update(override)
        except (OSError, json.JSONDecodeError):
            pass  # Ignore corrupt override; fall back to global
    return effective




def validate_agent_config(data: Any) -> List[str]:
    """Server-side validation of a full agent config dict.


    Returns a list of error strings; empty list means the config is valid.
    Accepts both Linux (/) and Windows (drive-letter) absolute paths so the
    central UI works regardless of where the agent runs.
    """
    if not isinstance(data, dict):
        return ["Config must be a JSON object"]


    errors: List[str] = []


    # Required scalar fields.
    for key in ("server_id", "snapshot_dir", "report_dir"):
        if not data.get(key):
            errors.append(f"Missing required field: '{key}'")


    # server_id must be filesystem-safe.
    sid = str(data.get("server_id", "")).strip()
    if sid and not all(c.isalnum() or c in "-_" for c in sid):
        errors.append("'server_id' must contain only letters, digits, hyphens, and underscores")


    def _is_abs(p: str) -> bool:
        """True if p looks like an absolute path on Linux OR Windows."""
        if not p:
            return False
        # Linux: starts with /
        if p.startswith("/"):
            return True
        # Windows: C:\ or C:/ style
        if len(p) >= 3 and p[1] == ":" and p[2] in ("/", "\\"):
            return True
        return False


    for key in ("snapshot_dir", "report_dir"):
        val = str(data.get(key, "")).strip()
        if val and not _is_abs(val):
            errors.append(f"'{key}' must be an absolute path (e.g. /path/to/dir or C:\\path\\to\\dir)")


    # paths list.
    paths = data.get("paths")
    if paths is None:
        errors.append("Missing required field: 'paths'")
    elif not isinstance(paths, list):
        errors.append("'paths' must be a list")
    elif len(paths) == 0:
        errors.append("'paths' must contain at least one monitored path")
    else:
        for i, entry in enumerate(paths):
            if not isinstance(entry, dict):
                errors.append(f"paths[{i}]: must be an object")
                continue
            p = str(entry.get("path", "")).strip()
            if not p:
                errors.append(f"paths[{i}]: 'path' is required")
            elif not _is_abs(p):
                errors.append(f"paths[{i}]: 'path' must be absolute")


    # Optional numeric fields.
    for key in ("max_content_size_bytes", "retention_count", "change_threshold"):
        val = data.get(key)
        if val is not None and not isinstance(val, (int, float)):
            errors.append(f"'{key}' must be a number if provided")


    return errors




def _warn_if_insecure_permissions(path: str) -> None:
    """Print a startup warning if the config file is group/world-readable."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            print(
                f"WARNING: {path} is group/world-readable (mode={oct(mode)}). "
                "It contains secrets — recommend 'chmod 600'.",
                file=sys.stderr,
                flush=True,
            )
    except OSError:
        pass








# ---------------------------------------------------------------------------
# Password hashing  (Task 3.1)
# ---------------------------------------------------------------------------








PBKDF2_ITERATIONS = 260_000




def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with PBKDF2-HMAC-SHA256.


    Returns ``salt_hex:hash_hex`` suitable for storage in platform_config.json.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{dk.hex()}"




def verify_password(plaintext: str, stored: str) -> bool:
    """Verify *plaintext* against a ``salt_hex:hash_hex`` stored value."""
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)








# ---------------------------------------------------------------------------
# Session cookies  (Task 3.2)
# ---------------------------------------------------------------------------








def make_session_cookie(username: str, secret: str, ttl_hours: int = SESSION_TTL_HOURS) -> str:
    """Return a signed session cookie value.


    Format: ``base64(json_payload).<hmac_hex>``
    where json_payload = ``{"u": username, "exp": unix_timestamp}``.
    """
    exp = int(time.time()) + ttl_hours * 3600
    payload_json = json.dumps({"u": username, "exp": exp}, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), "sha256").hexdigest()
    return f"{payload_b64}.{sig}"




def verify_session_cookie(cookie_value: str, secret: str) -> Optional[str]:
    """Verify a session cookie and return the username, or None if invalid/expired."""
    try:
        payload_b64, sig = cookie_value.rsplit(".", 1)
    except ValueError:
        return None
    expected_sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), "sha256").hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return str(payload["u"])
    except (ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Storage layer  (Tasks 4.1, 4.2, 4.6)
# ---------------------------------------------------------------------------








def store_push(data_dir: str, server_id: str, payload: Dict[str, Any]) -> None:
    """Persist an agent push payload to flat files under data_dir/server_id/.


    Writes:
      latest.json           -- full payload minus dashboard HTML and config (atomic)
      agent_config.json     -- agent's config.json contents pushed with snapshot
      latest_dashboard.html -- decoded agent HTML (atomic, omitted if absent)
      history/<ts>_<id>.json -- timestamped archive of latest.json
    """
    server_dir = os.path.join(data_dir, server_id)
    history_dir = os.path.join(server_dir, "history")
    os.makedirs(history_dir, exist_ok=True)


    # Strip dashboard HTML blob and config blob before storing in latest.json.
    storage_payload = {k: v for k, v in payload.items() if k not in ("dashboard_html_b64", "config")}
    storage_payload["last_seen"] = datetime.now(timezone.utc).isoformat()


    # Atomic write of latest.json
    latest_json = os.path.join(server_dir, "latest.json")
    _atomic_write_json(latest_json, storage_payload)


    # Store agent_config.json if the agent pushed its config.
    agent_cfg = payload.get("config")
    if isinstance(agent_cfg, dict):
        agent_config_path = os.path.join(server_dir, "agent_config.json")
        _atomic_write_json(agent_config_path, agent_cfg)


    # Decode and atomic write of dashboard HTML (if provided)
    dashboard_b64 = payload.get("dashboard_html_b64")
    if dashboard_b64:
        try:
            html_bytes = base64.b64decode(dashboard_b64)
            latest_html = os.path.join(server_dir, "latest_dashboard.html")
            _atomic_write_bytes(latest_html, html_bytes)
        except (ValueError, TypeError):
            pass  # Corrupt base64 — skip storing HTML


    # History entry (timestamped copy of storage_payload)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    history_file = os.path.join(history_dir, f"{ts}_{server_id}.json")
    _atomic_write_json(history_file, storage_payload)




def prune_history(data_dir: str, server_id: str, retention_count: int) -> None:
    """Delete the oldest history files beyond retention_count."""
    if retention_count <= 0:
        return
    history_dir = os.path.join(data_dir, server_id, "history")
    if not os.path.isdir(history_dir):
        return
    files = sorted(f for f in os.listdir(history_dir) if f.endswith(".json"))
    to_delete = files[: max(0, len(files) - retention_count)]
    for name in to_delete:
        try:
            os.unlink(os.path.join(history_dir, name))
        except OSError:
            pass




def health_status(latest: Dict[str, Any], stale_threshold_minutes: int) -> str:
    """Return 'healthy', 'stale', or 'unknown' based on last_seen timestamp."""
    last_seen_str = latest.get("last_seen") or latest.get("snapshot_at")
    if not last_seen_str:
        return "unknown"
    try:
        last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
        return "healthy" if age_seconds <= stale_threshold_minutes * 60 else "stale"
    except (ValueError, TypeError):
        return "unknown"




def _atomic_write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)




def _atomic_write_bytes(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Login form HTML
# ---------------------------------------------------------------------------








_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ServerSnap Central \u2014 Login</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;
       display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .card{{background:#1a1f2e;border:1px solid #2d3748;border-radius:12px;
        padding:2.5rem 2rem;width:100%;max-width:360px;box-shadow:0 8px 32px #0004}}
  h1{{font-size:1.4rem;margin-bottom:0.4rem;color:#7c9ef8}}
  p.sub{{font-size:.85rem;color:#94a3b8;margin-bottom:1.8rem}}
  label{{display:block;font-size:.8rem;color:#94a3b8;margin-bottom:.3rem}}
  input{{width:100%;padding:.6rem .8rem;border:1px solid #2d3748;border-radius:8px;
        background:#0f1117;color:#e2e8f0;font-size:.95rem;margin-bottom:1rem}}
  input:focus{{outline:none;border-color:#7c9ef8}}
  button{{width:100%;padding:.7rem;background:#7c9ef8;border:none;border-radius:8px;
         color:#0f1117;font-size:1rem;font-weight:600;cursor:pointer}}
  button:hover{{background:#6b8ff7}}
  .err{{color:#fc8181;font-size:.85rem;margin-bottom:1rem;
       padding:.5rem .8rem;background:#2d1515;border-radius:6px;border:1px solid #742a2a}}
</style>
</head>
<body>
<div class="card">
  <h1>ServerSnap Central</h1>
  <p class="sub">Sign in to monitor your fleet</p>
  {error_block}
  <form method="POST" action="/login" id="login-form">
    <label for="username">Username</label>
    <input id="username" name="username" type="text" autocomplete="username" required>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
  </form>
</div>
<script>
(function() {{
  // Normal top-level login: let the browser POST the form and receive the
  // Set-Cookie session as usual - nothing to do here.
  if (window.self === window.top) return;


  // Embedded in a (possibly cross-origin) iframe: the SameSite session
  // cookie set by a plain form POST may be silently rejected by the
  // browser. Exchange credentials for a signed JSON token instead and
  // keep it in sessionStorage; central.js attaches it as an X-Auth-Token
  // header on every API request.
  var form = document.getElementById("login-form");
  function showError(msg) {{
    var err = document.querySelector(".err");
    if (!err) {{
      err = document.createElement("div");
      err.className = "err";
      form.parentNode.insertBefore(err, form);
    }}
    err.textContent = msg;
  }}
  form.addEventListener("submit", function(e) {{
    e.preventDefault();
    var body = new URLSearchParams(new FormData(form));
    fetch("/login", {{
      method: "POST",
      body: body,
      headers: {{"Accept": "application/json"}}
    }}).then(function(res) {{
      return res.json().then(function(data) {{ return {{ok: res.ok, data: data}}; }});
    }}).then(function(r) {{
      if (r.ok && r.data.success) {{
        sessionStorage.setItem("sscentral_auth_token", r.data.token);
        window.location.href = "/central.html";
      }} else {{
        showError((r.data && r.data.error) || "Invalid username or password.");
      }}
    }}).catch(function() {{
      showError("Login request failed.");
    }});
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# URL decode helper (form POST parsing — stdlib only)
# ---------------------------------------------------------------------------








def _url_decode(s: str) -> str:
    """Decode a percent-encoded + URL-encoded string (form data)."""
    s = s.replace("+", " ")
    result: List[str] = []
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                result.append(chr(int(s[i + 1: i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        result.append(s[i])
        i += 1
    return "".join(result)








# ---------------------------------------------------------------------------
# Request handler  (Tasks 2.1 - 2.6, 3.3 - 3.7, 4.3 - 4.5)
# ---------------------------------------------------------------------------








class CentralRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the central platform server.


    Class attributes are set by the BoundHandler subclass in run_server().
    """


    # Populated by BoundHandler at startup:
    global_cfg: Dict[str, Any] = {}
    data_dir: str = ""
    public_dir: str = ""


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------


    def _clean_path(self) -> str:
        return self.path.split("?", 1)[0].split("#", 1)[0]


    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


    def _redirect(self, location: str, status: int = 302) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return b""
        return self.rfile.read(length)


    def _parse_cookies(self) -> Dict[str, str]:
        cookies: Dict[str, str] = {}
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies


    def _get_session_username(self) -> Optional[str]:
        """Return the authenticated username, or None.


        Checks the signed session cookie first (traditional top-level browser
        login). Falls back to an ``X-Auth-Token`` header carrying the same
        signed value - used by JS clients that can't rely on cookies, e.g.
        when central.html is embedded in a cross-origin <iframe> where the
        SameSite cookie policy would otherwise block the cookie from ever
        being sent.
        """
        secret = self.global_cfg.get("secret_key", "")


        cookie_val = self._parse_cookies().get(SESSION_COOKIE_NAME, "")
        if cookie_val:
            username = verify_session_cookie(cookie_val, secret)
            if username:
                return username


        token = self.headers.get("X-Auth-Token", "")
        if token:
            return verify_session_cookie(token, secret)


        return None


    def _require_auth(self) -> Optional[str]:
        """Return username if authenticated; otherwise respond and return None.


        JSON API routes (path starting with /api/) get a 401 JSON body so
        fetch()-based callers - including token-authenticated iframe clients
        that can't use the session cookie - can detect the failure directly
        instead of transparently following a redirect into the HTML login
        page. Plain page routes (e.g. the per-server dashboard HTML) still
        redirect to /login as before.
        """
        username = self._get_session_username()
        if username:
            return username
        if self._clean_path().startswith("/api/"):
            self._send_json({"error": "unauthorized"}, 401)
        else:
            self._redirect("/login")
        return None


    def _validate_api_key(self) -> bool:
        """Constant-time comparison of X-API-Key against configured key."""
        incoming = self.headers.get("X-API-Key", "")
        expected = self.global_cfg.get("api_key", "")
        return hmac.compare_digest(
            incoming.encode("utf-8"), expected.encode("utf-8")
        )


    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        sys.stdout.write(
            f"{self.address_string()} [{self.log_date_time_string()}] {fmt % args}\n"
        )
        sys.stdout.flush()


    # ------------------------------------------------------------------
    # GET dispatcher  (Task 2.1)
    # ------------------------------------------------------------------


    def do_GET(self) -> None:  # noqa: N802
        path = self._clean_path()


        if path in ("/", ""):
            self._redirect("/central.html")
            return


        if path == "/login":
            self._handle_get_login()
            return


        if path == "/logout":
            self._handle_logout()
            return


        if path == "/api/servers":
            if self._require_auth() is None:
                return
            self._handle_get_servers()
            return


        if path.startswith("/api/server/"):
            rest = path[len("/api/server/"):]
            parts = rest.split("/", 1)
            server_id = parts[0]
            sub = parts[1] if len(parts) > 1 else ""


            # pending-config is polled by the agent using the API key, NOT by the browser.
            if sub == "pending-config":
                if not self._validate_api_key():
                    self._send_json({"error": "unauthorized"}, 401)
                    return
                self._handle_get_pending_config(server_id)
                return
            if sub == "pending-baseline":
                if not self._validate_api_key():
                    self._send_json({"error": "unauthorized"}, 401)
                    return
                self._handle_get_pending_baseline(server_id)
                return


            # All other /api/server/* routes require a browser session.
            if self._require_auth() is None:
                return
            if sub == "config":
                self._handle_get_server_config(server_id)
            elif sub == "report-status":
                self._handle_get_report_status(server_id)
            elif sub == "audit-status":
                self._handle_get_audit_status(server_id)
            else:
                self._handle_get_server_detail(server_id)
            return


        if path.startswith("/server/") and path.endswith("/dashboard"):
            if self._require_auth() is None:
                return
            server_id = path[len("/server/"): -len("/dashboard")]
            self._handle_get_server_dashboard(server_id)
            return


        # Fall through to static file serving
        self._serve_static(path)


    # ------------------------------------------------------------------
    # POST dispatcher  (Task 2.1)
    # ------------------------------------------------------------------


    def do_POST(self) -> None:  # noqa: N802
        path = self._clean_path()


        if path == "/api/ingest":
            self._handle_post_ingest()
            return


        if path == "/login":
            self._handle_post_login()
            return


        if path.startswith("/api/server/") and path.endswith("/config"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/config")]
            self._handle_post_server_config(server_id)
            return


        if path.startswith("/api/server/") and path.endswith("/report-approve"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/report-approve")]
            self._handle_report_decision(server_id, "approve")
            return


        if path.startswith("/api/server/") and path.endswith("/report-reject"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/report-reject")]
            self._handle_report_decision(server_id, "reject")
            return


        if path.startswith("/api/server/") and path.endswith("/snapshot-approve"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/snapshot-approve")]
            self._handle_snapshot_decision(server_id, "APPROVED")
            return


        if path.startswith("/api/server/") and path.endswith("/snapshot-reject"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/snapshot-reject")]
            self._handle_snapshot_decision(server_id, "REJECTED")
            return


        if path.startswith("/api/server/") and path.endswith("/snapshot-compare"):
            if self._require_auth() is None:
                return
            server_id = path[len("/api/server/"): -len("/snapshot-compare")]
            self._handle_snapshot_compare(server_id)
            return


        self._send_json({"error": "not found"}, 404)


    def do_DELETE(self) -> None:  # noqa: N802
        path = self._clean_path()


        if path.startswith("/api/server/") and path.endswith("/pending-config"):
            # Agent-callable: accept API key auth (no browser session required).
            if not self._validate_api_key():
                self._send_json({"error": "unauthorized"}, 401)
                return
            server_id = path[len("/api/server/"): -len("/pending-config")]
            self._handle_delete_pending_config(server_id)
            return


        if path.startswith("/api/server/") and path.endswith("/pending-baseline"):
            if not self._validate_api_key():
                self._send_json({"error": "unauthorized"}, 401)
                return
            server_id = path[len("/api/server/"): -len("/pending-baseline")]
            self._handle_delete_pending_baseline(server_id)
            return


        self._send_json({"error": "not found"}, 404)


    # ------------------------------------------------------------------
    # Auth handlers  (Tasks 3.3 - 3.6)
    # ------------------------------------------------------------------


    def _handle_get_login(self) -> None:
        """GET /login — serve login form."""
        self._send_html(_LOGIN_HTML.format(error_block=""))


    def _handle_post_login(self) -> None:
        """POST /login — verify credentials, then respond with a session
        cookie (traditional browser form post) or a JSON token (iframe/API
        clients that send ``Accept: application/json``)."""
        body = self._read_body()
        fields: Dict[str, str] = {}
        for part in body.decode("utf-8", errors="replace").split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                fields[_url_decode(k)] = _url_decode(v)


        username = fields.get("username", "").strip()
        password = fields.get("password", "")
        users: Dict[str, str] = self.global_cfg.get("users", {})
        stored_hash = users.get(username, "")
        wants_json = "application/json" in self.headers.get("Accept", "")


        if stored_hash and verify_password(password, stored_hash):
            secret = self.global_cfg.get("secret_key", "")
            # Same signed value is used as both the cookie and the bearer
            # token - verify_session_cookie() validates either identically.
            cookie_val = make_session_cookie(username, secret)
            if wants_json:
                self._send_json({"success": True, "token": cookie_val})
                return
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={cookie_val}; Path=/; HttpOnly; SameSite=Lax",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            if wants_json:
                self._send_json(
                    {"success": False, "error": "Invalid username or password"}, 401
                )
                return
            error_block = '<div class="err">Invalid username or password.</div>'
            self._send_html(_LOGIN_HTML.format(error_block=error_block), status=401)


    def _handle_logout(self) -> None:
        """GET /logout — clear session cookie and redirect to /login."""
        self.send_response(302)
        self.send_header("Location", "/login")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; Max-Age=0",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()


    # ------------------------------------------------------------------
    # Ingest handler  (Task 2.2)
    # ------------------------------------------------------------------


    def _handle_post_ingest(self) -> None:
        """POST /api/ingest — receive snapshot payload from an agent."""
        if not self._validate_api_key():
            self._send_json({"error": "unauthorized"}, 401)
            return


        max_bytes = int(self.global_cfg.get("max_ingest_bytes", DEFAULT_MAX_INGEST_BYTES))
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > max_bytes:
            self._send_json({"error": "payload too large"}, 413)
            return


        body = self._read_body()
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._send_json({"error": "invalid JSON"}, 400)
            return


        server_id = str(payload.get("server_id", "")).strip()
        if not server_id:
            self._send_json({"error": "missing server_id in payload"}, 400)
            return


        try:
            store_push(self.data_dir, server_id, payload)
        except OSError as exc:
            self._send_json({"error": f"storage failure: {exc}"}, 500)
            return


        effective = get_effective_config(self.global_cfg, self.data_dir, server_id)
        retention = int(effective.get("history_retention_count", 30))
        prune_history(self.data_dir, server_id, retention)


        self._send_json({"ok": True})


    # ------------------------------------------------------------------
    # Server list / detail handlers  (Tasks 2.3, 2.4)
    # ------------------------------------------------------------------


    def _handle_get_servers(self) -> None:
        """GET /api/servers — list all known servers with health info."""
        servers: List[Dict[str, Any]] = []
        if not os.path.isdir(self.data_dir):
            self._send_json(servers)
            return


        for entry in sorted(os.listdir(self.data_dir)):
            server_dir = os.path.join(self.data_dir, entry)
            latest_path = os.path.join(server_dir, "latest.json")
            if not os.path.isdir(server_dir) or not os.path.isfile(latest_path):
                continue
            try:
                with open(latest_path, "r", encoding="utf-8") as fh:
                    latest = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue


            effective = get_effective_config(self.global_cfg, self.data_dir, entry)
            stale_threshold = int(effective.get("stale_threshold_minutes", 60))


            # Prefer baseline stats (cumulative) for card display; fall back to incremental.
            baseline_cs = latest.get("baseline_change_summary") or latest.get("change_summary", {})
            baseline_hc = latest.get("baseline_has_changes", latest.get("has_changes", False))


            servers.append({
                "server_id": entry,
                "hostname": latest.get("hostname", ""),
                "last_seen": latest.get("last_seen", latest.get("snapshot_at", "")),
                "has_changes": bool(baseline_hc),
                "change_summary": baseline_cs,
                "health": health_status(latest, stale_threshold),
            })


        self._send_json(servers)


    def _handle_get_server_detail(self, server_id: str) -> None:
        """GET /api/server/<id> — return latest.json content for one server."""
        latest_path = os.path.join(self.data_dir, server_id, "latest.json")
        if not os.path.isfile(latest_path):
            self._send_json({"error": "not found"}, 404)
            return
        try:
            with open(latest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 500)
            return
           
        effective = get_effective_config(self.global_cfg, self.data_dir, server_id)
        stale_threshold = int(effective.get("stale_threshold_minutes", 60))
        data["health"] = health_status(data, stale_threshold)
       
        self._send_json(data)


    # ------------------------------------------------------------------
    # Dashboard pass-through handler  (Task 2.5)
    # ------------------------------------------------------------------


    def _handle_get_server_dashboard(self, server_id: str) -> None:
        """GET /server/<id>/dashboard — serve latest_dashboard.html verbatim.


        The HTML is a static snapshot: visualize_report.py inlines the full
        contents of bin/public/visualize_report.js into it at generation
        time on the agent, and the agent pushes that HTML blob as-is. If an
        agent pushed its dashboard before a JS fix was deployed, the embedded
        JS may still call legacy non-server-scoped API paths (e.g.
        "/api/report-approve") that only exist on serve_dashboard.py, not
        here — causing 404s under central even though newer JS is correct.


        To avoid depending on every agent redeploying + re-pushing, patch
        window.fetch at serve time so any such legacy calls are transparently
        rewritten to this server's scoped endpoints. This is a no-op for
        dashboards built with already-fixed JS (which never calls the bare
        legacy paths once a server_id is detected).
        """
        html_path = os.path.join(self.data_dir, server_id, "latest_dashboard.html")
        if not os.path.isfile(html_path):
            self._send_json({"error": "dashboard not found for this server"}, 404)
            return
        try:
            with open(html_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            self._send_json({"error": str(exc)}, 500)
            return


        data = self._inject_central_fetch_shim(data, server_id)


        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


    @staticmethod
    def _inject_central_fetch_shim(html_bytes: bytes, server_id: str) -> bytes:
        """Append a small script rewriting legacy agent-local API paths to
        this central server's per-server scoped equivalents.


        Only exact-match legacy paths are rewritten, so already-fixed JS
        (which computes server-scoped URLs itself and never calls these bare
        paths when a server_id is present) is unaffected.
        """
        try:
            html_text = html_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return html_bytes


        sid_json = json.dumps(server_id)
        shim = f"""
<script>
(function() {{
  var _centralServerId = {sid_json};
  var _legacyMap = {{
    "/api/report-status": "/api/server/" + _centralServerId + "/report-status",
    "/api/report-approve": "/api/server/" + _centralServerId + "/report-approve",
    "/api/report-reject": "/api/server/" + _centralServerId + "/report-reject",
    "/api/audit-status": "/api/server/" + _centralServerId + "/audit-status",
    "/api/snapshot-approve": "/api/server/" + _centralServerId + "/snapshot-approve",
    "/api/snapshot-reject": "/api/server/" + _centralServerId + "/snapshot-reject"
  }};
  var _origFetch = window.fetch;
  window.fetch = function(input, init) {{
    if (typeof input === "string" && Object.prototype.hasOwnProperty.call(_legacyMap, input)) {{
      input = _legacyMap[input];
    }}
    return _origFetch.call(this, input, init);
  }};
}})();
</script>
"""
        # Must run BEFORE the embedded visualize_report.js, which calls
        # fetchReportStatus() synchronously as soon as it's parsed (it's the
        # last <script> before </body>). Inserting the shim there would be
        # too late — window.fetch would already have been called with the
        # legacy path. Inject right after <head> instead so our patched
        # window.fetch is in place before any other script on the page runs.
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", "<head>" + shim, 1)
        elif "</body>" in html_text:
            html_text = html_text.replace("</body>", shim + "</body>", 1)
        else:
            html_text += shim
        return html_text.encode("utf-8")




    # ------------------------------------------------------------------
    # Per-server config API  (Tasks 4.4, 4.5)
    # ------------------------------------------------------------------


    def _handle_get_server_config(self, server_id: str) -> None:
        """GET /api/server/<id>/config.


        Priority:
          1. agent_config.json  (full config pushed by the agent) — returned to the UI
          2. Falls back to effective platform override fields if no agent config is stored.
        Sensitive keys (api_key, secret_key, users, _comment_*) are always stripped.
        """
        server_dir = os.path.join(self.data_dir, server_id)
        agent_config_path = os.path.join(server_dir, "agent_config.json")


        if os.path.isfile(agent_config_path):
            try:
                with open(agent_config_path, "r", encoding="utf-8") as fh:
                    agent_cfg = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": f"Could not read agent config: {exc}"}, 500)
                return


            # Strip sensitive and comment-only keys.
            safe = {
                k: v for k, v in agent_cfg.items()
                if k not in AGENT_CONFIG_SENSITIVE_KEYS
                and not k.startswith(AGENT_CONFIG_COMMENT_PREFIX)
            }
            # Annotate so the UI knows this is a real agent config.
            safe["_source"] = "agent"
            self._send_json(safe)
            return


        # No agent config pushed yet — return platform overrides only.
        effective = get_effective_config(self.global_cfg, self.data_dir, server_id)
        safe = {
            k: v for k, v in effective.items()
            if k not in ("api_key", "secret_key", "users")
            and not k.startswith(AGENT_CONFIG_COMMENT_PREFIX)
        }
        safe["_source"] = "platform"
        self._send_json(safe)


    def _handle_post_server_config(self, server_id: str) -> None:
        """POST /api/server/<id>/config — validate and queue full agent config as pending_config.json.


        The agent will pick up pending_config.json on its next run, apply it to
        its local config.json, then DELETE /api/server/<id>/pending-config.
        """
        body = self._read_body()
        try:
            incoming = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._send_json({"error": "invalid JSON"}, 400)
            return


        # Server-side validation (replaces client-side checks).
        errors = validate_agent_config(incoming)
        if errors:
            self._send_json({"error": "Validation failed", "details": errors}, 400)
            return


        server_dir = os.path.join(self.data_dir, server_id)
        if not os.path.isdir(server_dir):
            self._send_json({"error": "server not found — agent must push at least one snapshot first"}, 404)
            return


        pending_path = os.path.join(server_dir, "pending_config.json")
        incoming["_queued_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(pending_path, incoming)
        self._send_json({"ok": True, "message": "Config queued — will be applied on the agent's next run"})


    def _handle_get_pending_config(self, server_id: str) -> None:
        """GET /api/server/<id>/pending-config — return pending_config.json if present (agent polling)."""
        pending_path = os.path.join(self.data_dir, server_id, "pending_config.json")
        if not os.path.isfile(pending_path):
            self._send_json({"pending": False})
            return
        try:
            with open(pending_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"pending": True, "config": data})


    def _handle_delete_pending_config(self, server_id: str) -> None:
        """DELETE /api/server/<id>/pending-config — agent acknowledges it has applied the config."""
        pending_path = os.path.join(self.data_dir, server_id, "pending_config.json")
        if not os.path.isfile(pending_path):
            self._send_json({"ok": True, "message": "No pending config to delete"})
            return
        try:
            os.unlink(pending_path)
        except OSError as exc:
            self._send_json({"error": f"Could not delete pending config: {exc}"}, 500)
            return
        self._send_json({"ok": True, "message": "Pending config acknowledged and removed"})


    # ------------------------------------------------------------------
    # Per-report approval API  (central-side mirror of serve_dashboard.py)
    # ------------------------------------------------------------------


    def _get_central_report_store(self, server_id: str):
        """Construct a ReportApprovalStore scoped to central_data/<id>/approvals.


        This is intentionally independent of any approvals store the agent
        keeps locally — central records the browser's decision immediately
        (for instant UI feedback) using only the data the browser already
        has, without needing filesystem access to the agent's report files.
        """
        approvals_dir = os.path.join(self.data_dir, server_id, "approvals")
        try:
            from report_approval_store import ReportApprovalStore  # type: ignore
        except ImportError:
            return None
        os.makedirs(approvals_dir, exist_ok=True)
        return ReportApprovalStore(server_id, approvals_dir)


    def _handle_get_report_status(self, server_id: str) -> None:
        """GET /api/server/<id>/report-status — per-report approval status."""
        store = self._get_central_report_store(server_id)
        if store is None:
            self._send_json({"error": "report_approval_store.py not found next to serve_central.py"}, 501)
            return
        try:
            self._send_json(store.get_status_summary())
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"Error retrieving report status: {exc}"}, 500)


    def _handle_report_decision(self, server_id: str, action: str) -> None:
        """POST /api/server/<id>/report-approve or /report-reject.


        The browser sends the report basename plus the metadata it already
        holds client-side (report_label/change_count/threshold, and — for
        approve only — the full report JSON) so central can record the
        decision and update its own golden snapshot without needing
        filesystem access to the agent's report files.
        """
        store = self._get_central_report_store(server_id)
        if store is None:
            self._send_json({"error": "report_approval_store.py not found next to serve_central.py"}, 501)
            return


        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return


        report_basename = str(data.get("report", "")).strip()
        if not report_basename:
            self._send_json({"error": "'report' field (report basename) is required"}, 400)
            return
        description = str(data.get("description", "")).strip()


        # Bootstrap/refresh the pending entry with whatever metadata the
        # browser already has, so approve()/reject() below always has a
        # record to act on (no-op if a decision was already made).
        store.set_pending(
            report_basename,
            str(data.get("report_label", report_basename)),
            int(data.get("change_count", 0) or 0),
            int(data.get("threshold", 0) or 0),
        )


        try:
            if action == "approve":
                ok = store.approve(report_basename, description)
                if ok:
                    report_data = data.get("report_data")
                    if isinstance(report_data, dict):
                        try:
                            from baseline_manager import BaselineManager  # type: ignore
                            baselines_dir = os.path.join(self.data_dir, server_id, "baselines")
                            os.makedirs(baselines_dir, exist_ok=True)
                            BaselineManager(server_id, baselines_dir).save_golden_snapshot(
                                report_data, str(data.get("report_label", report_basename))
                            )
                        except Exception:  # noqa: BLE001 - golden update is best-effort
                            pass
                message = f"Report '{report_basename}' approved." if ok else f"Report '{report_basename}' not found."
            else:
                ok = store.reject(report_basename, description)
                message = f"Report '{report_basename}' rejected." if ok else f"Report '{report_basename}' not found."


            self._send_json({
                "success": ok,
                "message": message,
                "status": store.get_status_summary(),
            })
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"Error processing {action} for '{report_basename}': {exc}"}, 500)


    def _audit_history_path(self, server_id: str) -> str:
        return os.path.join(self.data_dir, server_id, "audit_history.json")


    def _handle_get_audit_status(self, server_id: str) -> None:
        try:
            with open(self._audit_history_path(server_id), "r", encoding="utf-8") as fh:
                history = json.load(fh)
            if not isinstance(history, list):
                history = []
        except (OSError, json.JSONDecodeError):
            history = []
        self._send_json({"history": history})


    def _handle_snapshot_decision(self, server_id: str, action: str) -> None:
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
            snapshot_id = str(data.get("snapshot", "")).strip()
            user = str(data.get("user", "")).strip()
            reason = str(data.get("reason", "")).strip()
            if not snapshot_id or not user or not reason or os.path.basename(snapshot_id) != snapshot_id:
                raise ValueError("Snapshot, approver name, and reason are required")


            with open(os.path.join(self.data_dir, server_id, "latest.json"), "r", encoding="utf-8") as fh:
                latest = json.load(fh)
            snapshot = latest.get("snapshot")
            if action == "APPROVED" and not isinstance(snapshot, dict):
                raise ValueError("Central has no snapshot data for this server yet")


            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "snapshot_id": snapshot_id,
                "user": user,
                "reason": reason,
            }
            history_path = self._audit_history_path(server_id)
            try:
                with open(history_path, "r", encoding="utf-8") as fh:
                    history = json.load(fh)
                if not isinstance(history, list):
                    history = []
            except (OSError, json.JSONDecodeError):
                history = []
            history.append(record)
            _atomic_write_json(history_path, history)
		    
        self._send_json({"success": True, "history": history})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)



    def _snapshot_from_archive(self, server_id: str, snapshot_id: str) -> Dict[str, Any]:
        if os.path.basename(snapshot_id) != snapshot_id:
            raise ValueError("Invalid snapshot selection")
        for directory in (os.path.join(self.data_dir, server_id, "history"), os.path.join(self.data_dir, server_id)):
            if not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory), reverse=True):
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    snapshot = payload.get("snapshot")
                    if not isinstance(snapshot, dict):
                        continue
                    timestamp = datetime.fromisoformat(snapshot.get("generated_at", "")).strftime("%Y_%m_%d_%H_%M_%S")
                    if snapshot_id.endswith(f"_{timestamp}.json"):
                        return snapshot
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
        raise ValueError(f"Snapshot archive not found: {snapshot_id}")


    def _handle_snapshot_compare(self, server_id: str) -> None:
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
            base_id, target_id = str(data.get("base", "")), str(data.get("target", ""))
            if not base_id or not target_id or base_id == target_id:
                raise ValueError("Select two different reports")
            from server_snapshot import build_report, compare_snapshots  # type: ignore
            base = self._snapshot_from_archive(server_id, base_id)
            target = self._snapshot_from_archive(server_id, target_id)
            report = build_report(target, base_id, target_id, compare_snapshots(base, target))
            self._send_json({"report": report})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)


    def _handle_get_pending_baseline(self, server_id: str) -> None:
        path = os.path.join(self.data_dir, server_id, "pending_baseline.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                decision = json.load(fh)
        except FileNotFoundError:
            self._send_json({"pending": False})
            return
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"pending": True, "decision": decision})


    def _handle_delete_pending_baseline(self, server_id: str) -> None:
        try:
            os.remove(os.path.join(self.data_dir, server_id, "pending_baseline.json"))
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"ok": True})


    # ------------------------------------------------------------------
    # Static file serving  (Task 2.6)
    # ------------------------------------------------------------------


    def _serve_static(self, path: str) -> None:
        """Serve .html/.css/.js files from public_dir (whitelist only)."""
        filename = path.lstrip("/")
        if not filename:
            self._redirect("/central.html")
            return


        allowed_exts = (".html", ".css", ".js")
        _, ext = os.path.splitext(filename)
        if ext not in allowed_exts or "/" in filename or ".." in filename:
            self._send_json({"error": "not found"}, 404)
            return


        file_path = os.path.join(self.public_dir, filename)
        if not os.path.isfile(file_path):
            self._send_json({"error": "not found"}, 404)
            return


        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }
        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            self._send_json({"error": str(exc)}, 500)
            return


        self.send_response(200)
        self.send_header("Content-Type", content_types[ext])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)








# ---------------------------------------------------------------------------
# Server startup  (Tasks 2.1, 2.7)
# ---------------------------------------------------------------------------








def run_server(
    config_path: str,
    host: str,
    port: int,
    data_dir: str,
    public_dir: str,
    global_cfg: Dict[str, Any],
) -> int:
    """Start the ThreadingHTTPServer and block until shutdown."""


    class BoundHandler(CentralRequestHandler):
        pass


    BoundHandler.global_cfg = global_cfg
    BoundHandler.data_dir = data_dir
    BoundHandler.public_dir = public_dir


    try:
        httpd = http.server.ThreadingHTTPServer((host, port), BoundHandler)
    except OSError as exc:
        raise CentralError(f"Failed to bind {host}:{port}: {exc}") from exc


    def _shutdown(signum: int, _frame: Any) -> None:
        print(f"Received signal {signum}, shutting down...", flush=True)
        threading.Thread(target=httpd.shutdown, daemon=True).start()


    signal.signal(signal.SIGTERM, _shutdown)
    try:
        signal.signal(signal.SIGINT, _shutdown)
    except OSError:
        pass  # Windows: SIGINT handled via KeyboardInterrupt


    os.makedirs(data_dir, exist_ok=True)


    display_host = host if host != "0.0.0.0" else "<this-server-ip>"
    print(f"serve_central {SCRIPT_VERSION}", flush=True)
    print(f"Config:    {config_path}", flush=True)
    print(f"Data dir:  {data_dir}", flush=True)
    print(f"Public:    {public_dir}", flush=True)
    print(f"Listening: http://{display_host}:{port}/", flush=True)
    if host == "127.0.0.1":
        print(
            "Bound to localhost only. For remote access use an SSH tunnel:\n"
            f"  ssh -L {port}:127.0.0.1:{port} user@<this-server>",
            flush=True,
        )


    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        print("Server stopped.", flush=True)
    return 0




def main(argv: Optional[List[str]] = None) -> int:  # Task 2.7
    """Entry point for serve_central.py."""
    parser = argparse.ArgumentParser(
        description="ServerSnap Central — multi-server monitoring hub.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to platform_config.json (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: host in config, else 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: port in config, else 8090)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        dest="data_dir",
        help="Override central_data directory from config",
    )
    parser.add_argument(
        "--hash-password",
        metavar="PLAINTEXT",
        dest="hash_password",
        help=(
            "Print PBKDF2-HMAC-SHA256 hash for a password "
            "(for use in platform_config.json 'users' dict) and exit. "
            "Example: python3 serve_central.py --hash-password mysecret"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"serve_central {SCRIPT_VERSION}"
    )
    args = parser.parse_args(argv)


    # Task 6.2: --hash-password helper (implemented here so users don't
    # need a full config just to hash a password).
    if args.hash_password:
        print(hash_password(args.hash_password))
        return 0


    try:
        global_cfg = load_platform_config(args.config)
    except CentralError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


    # Task 3.7: warn on insecure file permissions
    _warn_if_insecure_permissions(args.config)


    host = args.host or global_cfg.get("host") or "127.0.0.1"
    port = args.port or global_cfg.get("port") or 8090


    data_dir = args.data_dir or global_cfg.get("data_dir") or os.path.join(
        os.path.dirname(os.path.abspath(args.config)), "central_data"
    )


    # public_dir: central.html/css/js live alongside this script in bin/public/
    public_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")


    try:
        return run_server(
            config_path=args.config,
            host=host,
            port=int(port),
            data_dir=data_dir,
            public_dir=public_dir,
            global_cfg=global_cfg,
        )
    except CentralError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0








if __name__ == "__main__":
    sys.exit(main())



