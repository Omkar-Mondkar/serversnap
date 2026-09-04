#!/usr/bin/env python3
"""
test_agent_push.py
==================
Tests for the push_to_platform() function added to server_snapshot.py.

Covers:
  - No push when platform not configured
  - push_always=False + no changes => skip
  - push_always=False + has_changes => sends
  - push_always=True + no changes => sends
  - Non-fatal on HTTP error (unreachable, 500, etc.)
  - API key sent as X-API-Key header
  - Payload includes server_id, hostname, has_changes, change_summary, snapshot
  - Dashboard HTML included (base64) when file exists
  - Dashboard HTML omitted (gracefully) when file missing

Run:
  python bin/test_agent_push.py -v
"""

import base64
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the function directly (we only need this one function)
from server_snapshot import push_to_platform, Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(platform=None, report_dir=None, server_id="web01") -> Config:
    return Config(
        server_id=server_id,
        hostname=f"{server_id}.example.com",
        paths=[],
        snapshot_dir="/tmp/snap",
        report_dir=report_dir or "/tmp/report",
        log_file=None,
        alerting={},
        platform=platform or {},
        max_content_size_bytes=5 * 1024 * 1024,
        retention_count=30,
        config_path="/tmp/config.json",
    )


def _snapshot():
    return {
        "server_id": "web01",
        "hostname": "web01.example.com",
        "snapshot_at": "2024-01-01T00:00:00Z",
    }


def _report(added=1, deleted=0, modified=2):
    return {"summary": {"added": added, "deleted": deleted, "modified": modified}}


def _platform_cfg(url="http://central:8090/api/ingest", api_key="key123", push_always=True):
    return {"url": url, "api_key": api_key, "push_always": push_always}


class FakeHTTPResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return b'{"ok": true}'


# ===========================================================================
# Tests
# ===========================================================================

class TestPushToPlatformSkipLogic(unittest.TestCase):

    def test_no_push_when_platform_not_configured(self):
        """Empty platform dict => silent no-op, no HTTP call."""
        cfg = _config(platform={})
        with patch("urllib.request.urlopen") as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
        mock_open.assert_not_called()

    def test_no_push_when_url_is_none(self):
        cfg = _config(platform={"url": None, "api_key": "k"})
        with patch("urllib.request.urlopen") as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
        mock_open.assert_not_called()

    def test_no_push_when_url_is_empty_string(self):
        cfg = _config(platform={"url": "", "api_key": "k"})
        with patch("urllib.request.urlopen") as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
        mock_open.assert_not_called()

    def test_push_always_false_no_changes_skips(self):
        """push_always=False and has_changes=False => no HTTP call."""
        cfg = _config(platform=_platform_cfg(push_always=False))
        with patch("urllib.request.urlopen") as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=False)
        mock_open.assert_not_called()

    def test_push_always_false_has_changes_sends(self):
        """push_always=False but has_changes=True => send."""
        cfg = _config(platform=_platform_cfg(push_always=False))
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(200)) as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
        mock_open.assert_called_once()

    def test_push_always_true_no_changes_sends(self):
        """push_always=True and has_changes=False => still send."""
        cfg = _config(platform=_platform_cfg(push_always=True))
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(200)) as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=False)
        mock_open.assert_called_once()

    def test_push_always_default_is_true(self):
        """push_always missing from config defaults to True => always sends."""
        platform = {"url": "http://central:8090/api/ingest", "api_key": "k"}
        cfg = _config(platform=platform)
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(200)) as mock_open:
            push_to_platform(cfg, _snapshot(), _report(), has_changes=False)
        mock_open.assert_called_once()


class TestPushToPlatformPayload(unittest.TestCase):

    def _capture_request(self, cfg, has_changes=True):
        """Return the Request object passed to urlopen."""
        captured = []

        def fake_open(req, timeout=None):
            captured.append(req)
            return FakeHTTPResponse(200)

        with patch("urllib.request.urlopen", side_effect=fake_open):
            push_to_platform(cfg, _snapshot(), _report(), has_changes=has_changes)

        self.assertEqual(len(captured), 1, "urlopen should be called exactly once")
        return captured[0]

    def test_posts_to_correct_url(self):
        url = "http://central:8090/api/ingest"
        cfg = _config(platform=_platform_cfg(url=url))
        req = self._capture_request(cfg)
        self.assertEqual(req.full_url, url)
        self.assertEqual(req.method, "POST")

    def test_api_key_in_header(self):
        cfg = _config(platform=_platform_cfg(api_key="my-secret-key"))
        req = self._capture_request(cfg)
        self.assertEqual(req.get_header("X-api-key"), "my-secret-key")

    def test_content_type_json(self):
        cfg = _config(platform=_platform_cfg())
        req = self._capture_request(cfg)
        self.assertIn("application/json", req.get_header("Content-type"))

    def test_payload_contains_server_id(self):
        cfg = _config(platform=_platform_cfg(), server_id="prod-db")
        req = self._capture_request(cfg)
        payload = json.loads(req.data)
        self.assertEqual(payload["server_id"], "prod-db")

    def test_payload_contains_has_changes(self):
        cfg = _config(platform=_platform_cfg())
        req = self._capture_request(cfg, has_changes=True)
        payload = json.loads(req.data)
        self.assertTrue(payload["has_changes"])

    def test_payload_contains_change_summary(self):
        cfg = _config(platform=_platform_cfg())
        req = self._capture_request(cfg)
        payload = json.loads(req.data)
        self.assertIn("change_summary", payload)
        self.assertEqual(payload["change_summary"]["added"], 1)

    def test_payload_contains_snapshot(self):
        cfg = _config(platform=_platform_cfg())
        req = self._capture_request(cfg)
        payload = json.loads(req.data)
        self.assertIn("snapshot", payload)


class TestPushToPlatformDashboardHTML(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _capture_payload(self, cfg):
        captured = []

        def fake_open(req, timeout=None):
            captured.append(json.loads(req.data))
            return FakeHTTPResponse(200)

        with patch("urllib.request.urlopen", side_effect=fake_open):
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)

        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_dashboard_html_included_when_file_exists(self):
        # Write a fake latest_dashboard_web01.html
        dash_dir = os.path.join(self.tmp, "dashboard")
        os.makedirs(dash_dir)
        html_content = b"<html><body>my dashboard</body></html>"
        with open(os.path.join(dash_dir, "latest_dashboard_web01.html"), "wb") as f:
            f.write(html_content)

        cfg = _config(platform=_platform_cfg(), report_dir=self.tmp, server_id="web01")
        payload = self._capture_payload(cfg)

        self.assertIn("dashboard_html_b64", payload)
        decoded = base64.b64decode(payload["dashboard_html_b64"])
        self.assertEqual(decoded, html_content)

    def test_dashboard_html_omitted_when_file_missing(self):
        # No dashboard file exists
        cfg = _config(platform=_platform_cfg(), report_dir=self.tmp, server_id="web01")
        payload = self._capture_payload(cfg)
        self.assertNotIn("dashboard_html_b64", payload)

    def test_push_still_succeeds_without_dashboard(self):
        """Absence of dashboard HTML must not block the push."""
        cfg = _config(platform=_platform_cfg(), report_dir=self.tmp)
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(200)) as mock_open:
            # No exception raised
            push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
        mock_open.assert_called_once()


class TestPushToPlatformErrorHandling(unittest.TestCase):
    """All errors must be non-fatal (no exception propagated)."""

    def _run(self, side_effect):
        cfg = _config(platform=_platform_cfg())
        with patch("urllib.request.urlopen", side_effect=side_effect):
            # Should NOT raise
            try:
                push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
            except Exception as exc:
                self.fail(f"push_to_platform raised {type(exc).__name__}: {exc}")

    def test_url_error_non_fatal(self):
        self._run(urllib.error.URLError("connection refused"))

    def test_http_error_500_non_fatal(self):
        self._run(urllib.error.HTTPError(
            "http://x", 500, "Internal Server Error", {}, None
        ))

    def test_http_error_401_non_fatal(self):
        self._run(urllib.error.HTTPError(
            "http://x", 401, "Unauthorized", {}, None
        ))

    def test_os_error_non_fatal(self):
        self._run(OSError("network unreachable"))

    def test_non_2xx_response_non_fatal(self):
        """Server returns 503 but doesn't raise — should log warning, not raise."""
        cfg = _config(platform=_platform_cfg())
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(503)):
            try:
                push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
            except Exception as exc:
                self.fail(f"push_to_platform raised {type(exc).__name__}: {exc}")

    def test_corrupt_dashboard_html_file_non_fatal(self):
        """If dashboard file is unreadable, push should still complete."""
        tmp = tempfile.mkdtemp()
        try:
            dash_dir = os.path.join(tmp, "dashboard")
            os.makedirs(dash_dir)
            path = os.path.join(dash_dir, "latest_dashboard_web01.html")
            with open(path, "wb") as f:
                f.write(b"<html/>")
            cfg = _config(platform=_platform_cfg(), report_dir=tmp, server_id="web01")
            # Mock open to simulate read failure
            with patch("builtins.open", side_effect=OSError("read error")):
                with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(200)):
                    try:
                        push_to_platform(cfg, _snapshot(), _report(), has_changes=True)
                    except Exception as exc:
                        self.fail(f"Raised unexpectedly: {exc}")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
