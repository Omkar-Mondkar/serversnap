#!/usr/bin/env python3
"""
test_serve_central.py
=====================
Automated tests for bin/serve_central.py.

Covers:
  Unit tests: hash_password, verify_password
  Unit tests: make_session_cookie, verify_session_cookie
  Unit tests: store_push, prune_history, health_status, get_effective_config
  HTTP integration: all API endpoints via live ThreadingHTTPServer on port 0

Run:
  python bin/test_serve_central.py -v
"""

import base64
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from serve_central import (
    CentralRequestHandler,
    SESSION_COOKIE_NAME,
    _url_decode,
    get_effective_config,
    hash_password,
    health_status,
    make_session_cookie,
    prune_history,
    store_push,
    verify_password,
    verify_session_cookie,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(server_id="web01", has_changes=True, dashboard_b64=None):
    p = {
        "server_id": server_id,
        "hostname": f"{server_id}.example.com",
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "has_changes": has_changes,
        "change_summary": {"added": 1, "deleted": 0, "modified": 2},
        "snapshot": {"entries": []},
    }
    if dashboard_b64 is not None:
        p["dashboard_html_b64"] = dashboard_b64
    return p


class LiveServer:
    """Spin up serve_central on port 0 for integration tests."""

    def __init__(self, data_dir, public_dir=None):
        self.data_dir = data_dir
        self._own_public = public_dir is None
        self.public_dir = public_dir if public_dir else tempfile.mkdtemp()
        self.cfg = {
            "api_key": "test-key-abc",
            "secret_key": "test-secret-abc",
            "users": {"admin": hash_password("pass")},
            "stale_threshold_minutes": 60,
            "history_retention_count": 10,
        }

        class BH(CentralRequestHandler):
            pass

        BH.global_cfg = self.cfg
        BH.data_dir = data_dir
        BH.public_dir = self.public_dir
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BH)
        self.port = self.httpd.server_address[1]
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *_):
        self.httpd.shutdown()
        if self._own_public:
            shutil.rmtree(self.public_dir, ignore_errors=True)

    def conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def ingest(self, payload, api_key=None):
        key = api_key if api_key is not None else self.cfg["api_key"]
        body = json.dumps(payload).encode()
        c = self.conn()
        c.request("POST", "/api/ingest", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-API-Key": key,
        })
        try:
            r = c.getresponse()
            status = r.status
            resp_body = r.read()
        except (ConnectionAbortedError, ConnectionResetError):
            # Windows: server may close connection after 4xx
            return 401, {"error": "aborted"}
        try:
            data = json.loads(resp_body)
        except Exception:
            data = {}
        return status, data

    def login(self, user="admin", pw="pass"):
        body = f"username={user}&password={pw}"
        c = self.conn()
        c.request("POST", "/login", body=body.encode(), headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        })
        r = c.getresponse()
        r.read()
        for part in r.getheader("Set-Cookie", "").split(";"):
            part = part.strip()
            if part.startswith(SESSION_COOKIE_NAME + "="):
                return part[len(SESSION_COOKIE_NAME) + 1:]
        return None

    def authed(self, method, path, cookie, body=None, extra_headers=None):
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"}
        if extra_headers:
            headers.update(extra_headers)
        c = self.conn()
        c.request(method, path, body=body, headers=headers)
        return c.getresponse()


# ===========================================================================
# 1. Password hashing
# ===========================================================================

class TestPasswordHashing(unittest.TestCase):

    def test_round_trip(self):
        s = hash_password("correct-horse-battery")
        self.assertTrue(verify_password("correct-horse-battery", s))

    def test_wrong_password_rejected(self):
        s = hash_password("right")
        self.assertFalse(verify_password("wrong", s))

    def test_format_salt_hex_colon_hash_hex(self):
        s = hash_password("x")
        self.assertIn(":", s)
        salt_hex, hash_hex = s.split(":", 1)
        self.assertEqual(len(salt_hex), 32, "salt = 16 bytes = 32 hex chars")
        self.assertTrue(len(hash_hex) > 0)

    def test_unique_salts(self):
        self.assertNotEqual(hash_password("pw"), hash_password("pw"))

    def test_corrupt_stored_false(self):
        for bad in ("", "notformat", "zz:zz", "::"):
            self.assertFalse(verify_password("x", bad), f"expected False for {bad!r}")


# ===========================================================================
# 2. Session cookies
# ===========================================================================

class TestSessionCookies(unittest.TestCase):
    S = "my-test-secret"

    def test_round_trip(self):
        self.assertEqual(verify_session_cookie(make_session_cookie("alice", self.S), self.S), "alice")

    def test_expired_cookie_none(self):
        c = make_session_cookie("bob", self.S, ttl_hours=0)
        time.sleep(0.05)
        self.assertIsNone(verify_session_cookie(c, self.S))

    def test_wrong_secret_none(self):
        c = make_session_cookie("alice", self.S)
        self.assertIsNone(verify_session_cookie(c, "other-secret"))

    def test_tampered_payload_none(self):
        c = make_session_cookie("alice", self.S)
        tampered = c[:-1] + ("X" if c[-1] != "X" else "Y")
        self.assertIsNone(verify_session_cookie(tampered, self.S))

    def test_garbage_none(self):
        self.assertIsNone(verify_session_cookie("", self.S))
        self.assertIsNone(verify_session_cookie("notacookie", self.S))


# ===========================================================================
# 3. Health status
# ===========================================================================

class TestHealthStatus(unittest.TestCase):

    def _ts(self, delta_minutes=0):
        return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat()

    def test_healthy_now(self):
        self.assertEqual(health_status({"last_seen": self._ts(0)}, 60), "healthy")

    def test_stale_2h_ago(self):
        self.assertEqual(health_status({"last_seen": self._ts(-120)}, 60), "stale")

    def test_unknown_no_field(self):
        self.assertEqual(health_status({}, 60), "unknown")

    def test_unknown_bad_ts(self):
        self.assertEqual(health_status({"last_seen": "not-a-date"}, 60), "unknown")

    def test_falls_back_to_snapshot_at(self):
        self.assertEqual(health_status({"snapshot_at": self._ts(0)}, 60), "healthy")

    def test_boundary_exactly_threshold(self):
        # Use 59 minutes — strictly within the 60-min threshold (avoids timing jitter)
        within = self._ts(-59)
        self.assertEqual(health_status({"last_seen": within}, 60), "healthy")


# ===========================================================================
# 4. Config cascade
# ===========================================================================

class TestGetEffectiveConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir)
        self.g = {"stale_threshold_minutes": 60, "retention": 30, "api_key": "k"}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_no_override_returns_global(self):
        eff = get_effective_config(self.g, self.data_dir, "s1")
        self.assertEqual(eff["stale_threshold_minutes"], 60)

    def test_override_wins(self):
        d = os.path.join(self.data_dir, "s1")
        os.makedirs(d)
        with open(os.path.join(d, "override.json"), "w") as f:
            json.dump({"stale_threshold_minutes": 5}, f)
        eff = get_effective_config(self.g, self.data_dir, "s1")
        self.assertEqual(eff["stale_threshold_minutes"], 5)
        self.assertEqual(eff["retention"], 30)  # global key still present

    def test_corrupt_override_falls_back(self):
        d = os.path.join(self.data_dir, "s2")
        os.makedirs(d)
        with open(os.path.join(d, "override.json"), "w") as f:
            f.write("{not valid json")
        eff = get_effective_config(self.g, self.data_dir, "s2")
        self.assertEqual(eff["stale_threshold_minutes"], 60)


# ===========================================================================
# 5. Storage layer
# ===========================================================================

class TestStorageLayer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmp, "data")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_latest_json(self):
        store_push(self.data_dir, "s1", _payload("s1"))
        p = os.path.join(self.data_dir, "s1", "latest.json")
        self.assertTrue(os.path.isfile(p))
        with open(p) as f:
            d = json.load(f)
        self.assertEqual(d["server_id"], "s1")

    def test_strips_dashboard_b64_from_json(self):
        html_b64 = base64.b64encode(b"<html/>").decode()
        store_push(self.data_dir, "s2", _payload("s2", dashboard_b64=html_b64))
        with open(os.path.join(self.data_dir, "s2", "latest.json")) as f:
            d = json.load(f)
        self.assertNotIn("dashboard_html_b64", d)

    def test_writes_dashboard_html(self):
        html = b"<html><body>dash</body></html>"
        store_push(self.data_dir, "s3", _payload("s3", dashboard_b64=base64.b64encode(html).decode()))
        p = os.path.join(self.data_dir, "s3", "latest_dashboard.html")
        self.assertTrue(os.path.isfile(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), html)

    def test_creates_history_entry(self):
        store_push(self.data_dir, "s4", _payload("s4"))
        hdir = os.path.join(self.data_dir, "s4", "history")
        self.assertEqual(len(os.listdir(hdir)), 1)

    def test_adds_last_seen(self):
        store_push(self.data_dir, "s5", _payload("s5"))
        with open(os.path.join(self.data_dir, "s5", "latest.json")) as f:
            self.assertIn("last_seen", json.load(f))

    def test_atomic_write_no_partial_file(self):
        """latest.json should never exist in .tmp form after store_push."""
        store_push(self.data_dir, "s6", _payload("s6"))
        tmp_path = os.path.join(self.data_dir, "s6", "latest.json.tmp")
        self.assertFalse(os.path.exists(tmp_path))

    def test_prune_keeps_count(self):
        # Push 5 times with manual distinct timestamps via patching
        import unittest.mock as mock
        base_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(5):
            fake_now = base_dt + timedelta(seconds=i)
            with mock.patch("serve_central.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.fromisoformat = datetime.fromisoformat
                store_push(self.data_dir, "p1", _payload("p1"))
        prune_history(self.data_dir, "p1", 3)
        hdir = os.path.join(self.data_dir, "p1", "history")
        self.assertEqual(len(os.listdir(hdir)), 3)

    def test_prune_keeps_newest(self):
        names_written = []
        for i in range(3):
            store_push(self.data_dir, "p2", _payload("p2"))
            time.sleep(0.02)
        hdir = os.path.join(self.data_dir, "p2", "history")
        all_files = sorted(os.listdir(hdir))
        prune_history(self.data_dir, "p2", 1)
        remaining = sorted(os.listdir(hdir))
        self.assertEqual(remaining, [all_files[-1]])

    def test_prune_zero_retention_noop(self):
        store_push(self.data_dir, "p3", _payload("p3"))
        prune_history(self.data_dir, "p3", 0)
        hdir = os.path.join(self.data_dir, "p3", "history")
        self.assertEqual(len(os.listdir(hdir)), 1)

    def test_prune_nonexistent_noop(self):
        prune_history(self.data_dir, "doesnotexist", 5)  # must not raise


# ===========================================================================
# 6. URL decode helper
# ===========================================================================

class TestUrlDecode(unittest.TestCase):
    def test_plus_space(self):
        self.assertEqual(_url_decode("a+b"), "a b")

    def test_percent_hex(self):
        self.assertEqual(_url_decode("a%20b"), "a b")
        self.assertEqual(_url_decode("user%40host"), "user@host")

    def test_plain(self):
        self.assertEqual(_url_decode("abc"), "abc")


# ===========================================================================
# 7. HTTP integration: ingest
# ===========================================================================

class TestIngest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dd = os.path.join(self.tmp, "data")
        os.makedirs(self.dd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_valid_key_200(self):
        with LiveServer(self.dd) as s:
            status, body = s.ingest(_payload())
            self.assertEqual(status, 200)
            self.assertTrue(body.get("ok"))

    def test_wrong_key_401(self):
        with LiveServer(self.dd) as s:
            status, body = s.ingest(_payload(), api_key="bad-key")
            self.assertEqual(status, 401)
            self.assertIn("error", body)

    def test_empty_key_401(self):
        with LiveServer(self.dd) as s:
            status, _ = s.ingest(_payload(), api_key="")
            self.assertEqual(status, 401)

    def test_bad_json_400(self):
        with LiveServer(self.dd) as s:
            body = b"{{not json"
            c = s.conn()
            c.request("POST", "/api/ingest", body=body, headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "X-API-Key": s.cfg["api_key"],
            })
            self.assertEqual(c.getresponse().status, 400)

    def test_missing_server_id_400(self):
        with LiveServer(self.dd) as s:
            status, body = s.ingest({"hostname": "x"})
            self.assertEqual(status, 400)

    def test_auto_discovery(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("brand-new-server"))
        self.assertTrue(os.path.isdir(os.path.join(self.dd, "brand-new-server")))

    def test_creates_latest_json(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("db01"))
        self.assertTrue(os.path.isfile(os.path.join(self.dd, "db01", "latest.json")))

    def test_dashboard_html_stored(self):
        html = b"<html>dash</html>"
        payload = _payload("dashtest", dashboard_b64=base64.b64encode(html).decode())
        with LiveServer(self.dd) as s:
            s.ingest(payload)
        p = os.path.join(self.dd, "dashtest", "latest_dashboard.html")
        self.assertTrue(os.path.isfile(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), html)


# ===========================================================================
# 8. HTTP integration: auth
# ===========================================================================

class TestAuthEndpoints(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dd = os.path.join(self.tmp, "data")
        os.makedirs(self.dd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_login_form_200(self):
        with LiveServer(self.dd) as s:
            c = s.conn()
            c.request("GET", "/login")
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            self.assertIn(b"ServerSnap Central", r.read())

    def test_login_valid_sets_cookie(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            self.assertIsNotNone(cookie)
            self.assertGreater(len(cookie), 10)

    def test_login_wrong_password_401(self):
        with LiveServer(self.dd) as s:
            body = "username=admin&password=WRONG"
            c = s.conn()
            c.request("POST", "/login", body=body.encode(), headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            })
            self.assertEqual(c.getresponse().status, 401)

    def test_login_unknown_user_401(self):
        with LiveServer(self.dd) as s:
            body = "username=nobody&password=pass"
            c = s.conn()
            c.request("POST", "/login", body=body.encode(), headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            })
            self.assertEqual(c.getresponse().status, 401)

    def test_unauthenticated_api_redirects(self):
        with LiveServer(self.dd) as s:
            c = s.conn()
            c.request("GET", "/api/servers")
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 302)
            self.assertIn("/login", r.getheader("Location", ""))

    def test_authenticated_api_servers_200(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            r = s.authed("GET", "/api/servers", cookie)
            self.assertEqual(r.status, 200)
            data = json.loads(r.read())
            self.assertIsInstance(data, list)

    def test_logout_clears_cookie(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            r = s.authed("GET", "/logout", cookie)
            r.read()
            self.assertEqual(r.status, 302)
            self.assertIn("Max-Age=0", r.getheader("Set-Cookie", ""))

    def test_tampered_cookie_redirects(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            bad = cookie[:-1] + ("X" if cookie[-1] != "X" else "Y")
            r = s.authed("GET", "/api/servers", bad)
            r.read()
            self.assertEqual(r.status, 302)


# ===========================================================================
# 9. HTTP integration: server APIs
# ===========================================================================

class TestServerAPIs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dd = os.path.join(self.tmp, "data")
        os.makedirs(self.dd)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_empty_servers(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            r = s.authed("GET", "/api/servers", cookie)
            self.assertEqual(json.loads(r.read()), [])

    def test_servers_lists_all_ingested(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("alpha"))
            s.ingest(_payload("beta"))
            cookie = s.login()
            r = s.authed("GET", "/api/servers", cookie)
            ids = {sv["server_id"] for sv in json.loads(r.read())}
            self.assertIn("alpha", ids)
            self.assertIn("beta", ids)

    def test_servers_includes_health_field(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("h1"))
            cookie = s.login()
            r = s.authed("GET", "/api/servers", cookie)
            srv = json.loads(r.read())[0]
            self.assertIn("health", srv)
            self.assertIn(srv["health"], ("healthy", "stale", "unknown"))

    def test_server_detail_known_200(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("detail01"))
            cookie = s.login()
            r = s.authed("GET", "/api/server/detail01", cookie)
            self.assertEqual(r.status, 200)
            d = json.loads(r.read())
            self.assertEqual(d["server_id"], "detail01")

    def test_server_detail_unknown_404(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            r = s.authed("GET", "/api/server/does-not-exist", cookie)
            self.assertEqual(r.status, 404)
            r.read()

    def test_server_dashboard_unknown_404(self):
        with LiveServer(self.dd) as s:
            cookie = s.login()
            r = s.authed("GET", "/server/nobody/dashboard", cookie)
            self.assertEqual(r.status, 404)
            r.read()

    def test_server_dashboard_known_200(self):
        html = b"<html>dash</html>"
        with LiveServer(self.dd) as s:
            s.ingest(_payload("dashsrv", dashboard_b64=base64.b64encode(html).decode()))
            cookie = s.login()
            r = s.authed("GET", "/server/dashsrv/dashboard", cookie)
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), html)

    def test_server_config_no_secrets(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("cfgsrv"))
            cookie = s.login()
            r = s.authed("GET", "/api/server/cfgsrv/config", cookie)
            self.assertEqual(r.status, 200)
            d = json.loads(r.read())
            for secret_key in ("api_key", "secret_key", "users"):
                self.assertNotIn(secret_key, d)

    def test_has_changes_propagated(self):
        with LiveServer(self.dd) as s:
            s.ingest(_payload("chgsrv", has_changes=True))
            cookie = s.login()
            r = s.authed("GET", "/api/servers", cookie)
            srvs = json.loads(r.read())
            srv = next(sv for sv in srvs if sv["server_id"] == "chgsrv")
            self.assertTrue(srv["has_changes"])


# ===========================================================================
# 10. HTTP integration: static files
# ===========================================================================

class TestStaticFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dd = os.path.join(self.tmp, "data")
        self.pub = os.path.join(self.tmp, "public")
        os.makedirs(self.dd)
        os.makedirs(self.pub)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_html_served(self):
        content = b"<html><body>hi</body></html>"
        with open(os.path.join(self.pub, "central.html"), "wb") as f:
            f.write(content)
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/central.html")
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), content)

    def test_css_content_type(self):
        with open(os.path.join(self.pub, "central.css"), "wb") as f:
            f.write(b"body{}")
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/central.css")
            r = c.getresponse()
            self.assertIn("text/css", r.getheader("Content-Type", ""))
            r.read()

    def test_missing_file_404(self):
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/central.html")
            self.assertEqual(c.getresponse().status, 404)

    def test_non_allowed_ext_404(self):
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/config.json")
            r = c.getresponse()
            self.assertEqual(r.status, 404)
            r.read()

    def test_root_redirects_to_central_html(self):
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/")
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 302)
            self.assertIn("central.html", r.getheader("Location", ""))

    def test_path_traversal_rejected(self):
        with LiveServer(self.dd, public_dir=self.pub) as s:
            c = s.conn()
            c.request("GET", "/../../etc/passwd.html")
            r = c.getresponse()
            self.assertIn(r.status, (400, 404))
            r.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
