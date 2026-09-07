#!/usr/bin/env python3
"""
test_app_and_report_drift.py
============================
Unit and integration tests verifying:
1. BaselineManager app diff calculation across executables, scripts, and symlinks.
2. BaselineManager app comparison ignores timestamps (zero false positives).
3. ApprovalAPIHandler and serve_dashboard support for category "app" and "network".
4. visualize_report dashboard embedding of badges, app/network drift sections, and audit containers.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_manager import BaselineManager
from approval_api import ApprovalAPIHandler
from visualize_report import _compute_threshold_data, build_dashboard_html, analyze_configured_paths


class TestAppAndReportDrift(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="serversnap_drift_test_")
        self.server_id = "test-srv-02"
        self.baselines_dir = os.path.join(self.test_dir, "baselines")
        self.approvals_dir = os.path.join(self.test_dir, "approvals")
        os.makedirs(self.baselines_dir, exist_ok=True)
        os.makedirs(self.approvals_dir, exist_ok=True)

        self.bm = BaselineManager(self.server_id, self.baselines_dir)
        self.handler = ApprovalAPIHandler(self.server_id, self.approvals_dir, self.baselines_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_app_baseline_no_false_positives_on_timestamp(self):
        """Verify dynamic timestamps in app snapshots do NOT cause false drift positives."""
        app_snap_1 = {
            "total_binaries": 2,
            "executables": [
                {"name": "app1", "path": "/usr/local/bin/app1", "type": "file", "size": 1024, "permissions": "755", "subtype": "binary"}
            ],
            "scripts": [
                {"name": "task.sh", "path": "/usr/local/bin/task.sh", "type": "file", "size": 256, "permissions": "755", "subtype": "script"}
            ],
            "symlinks": [],
            "timestamp": "2026-09-07T10:00:00Z"
        }
        self.bm.save_baseline("app", app_snap_1)

        # Same binaries, later timestamp
        app_snap_2 = {
            "total_binaries": 2,
            "executables": [
                {"name": "app1", "path": "/usr/local/bin/app1", "type": "file", "size": 1024, "permissions": "755", "subtype": "binary"}
            ],
            "scripts": [
                {"name": "task.sh", "path": "/usr/local/bin/task.sh", "type": "file", "size": 256, "permissions": "755", "subtype": "script"}
            ],
            "symlinks": [],
            "timestamp": "2026-09-07T11:00:00Z"
        }

        has_changes, diff = self.bm.compare_with_baseline("app", app_snap_2)
        self.assertFalse(has_changes)
        self.assertEqual(diff.get("status"), "no_changes")

    def test_app_baseline_detects_added_removed_modified(self):
        """Verify adding, removing, or modifying an executable/script/symlink is correctly detected."""
        baseline_snap = {
            "total_binaries": 2,
            "executables": [
                {"name": "app1", "path": "/usr/local/bin/app1", "type": "file", "size": 1024, "permissions": "755", "subtype": "binary"}
            ],
            "scripts": [
                {"name": "old_tool.sh", "path": "/usr/local/bin/old_tool.sh", "type": "file", "size": 500, "permissions": "755", "subtype": "script"}
            ],
            "symlinks": [
                {"name": "link1", "path": "/usr/local/bin/link1", "type": "symlink", "target": "/opt/v1"}
            ],
            "timestamp": "2026-09-07T10:00:00Z"
        }
        self.bm.save_baseline("app", baseline_snap)

        new_snap = {
            "total_binaries": 3,
            "executables": [
                # app1 modified size and permissions
                {"name": "app1", "path": "/usr/local/bin/app1", "type": "file", "size": 2048, "permissions": "700", "subtype": "binary"},
                # new_app added
                {"name": "new_app", "path": "/usr/local/bin/new_app", "type": "file", "size": 300, "permissions": "755", "subtype": "binary"}
            ],
            "scripts": [
                # old_tool.sh removed
            ],
            "symlinks": [
                # link1 target updated
                {"name": "link1", "path": "/usr/local/bin/link1", "type": "symlink", "target": "/opt/v2"}
            ],
            "timestamp": "2026-09-07T11:00:00Z"
        }

        has_changes, diff = self.bm.compare_with_baseline("app", new_snap)
        self.assertTrue(has_changes)
        self.assertEqual(len(diff["added_apps"]), 1)
        self.assertEqual(diff["added_apps"][0]["name"], "new_app")

        self.assertEqual(len(diff["removed_apps"]), 1)
        self.assertEqual(diff["removed_apps"][0]["name"], "old_tool.sh")

        self.assertEqual(len(diff["updated_apps"]), 2)
        updated_names = {u["name"] for u in diff["updated_apps"]}
        self.assertIn("app1", updated_names)
        self.assertIn("link1", updated_names)

    def test_approval_api_app_and_network(self):
        """Verify approve and reject workflows for both 'app' and 'network' categories."""
        # 1. Approve app
        app_data = {"executables": [{"name": "app1", "path": "/bin/app1"}]}
        ok, msg = self.handler.approve_changes("app", app_data, user="Alice", reason="Ticket-99")
        self.assertTrue(ok)
        self.assertIn("app", msg)

        status = self.handler.get_approval_status()
        self.assertEqual(status["categories"]["app"]["status"], "approved")

        # Check history recorded user & reason
        hist = self.handler.get_approval_history()
        self.assertGreaterEqual(hist["total_decisions"], 1)
        self.assertEqual(hist["recent"][-1]["user"], "Alice")
        self.assertEqual(hist["recent"][-1]["reason"], "Ticket-99")

        # 2. Reject network
        ok_net, msg_net = self.handler.reject_changes("network", user="Bob", reason="Unauthorized drift")
        self.assertTrue(ok_net)
        self.assertIn("network", msg_net)

        status_after = self.handler.get_approval_status()
        self.assertEqual(status_after["categories"]["network"]["status"], "rejected")

    def test_threshold_data_aggregates_all_drifts(self):
        """Verify _compute_threshold_data includes files + apps + network in total change count."""
        entries = [{
            "file": os.path.join(self.test_dir, "report_test-srv-02_2026_09_07_12_00.json"),
            "label": "Report 1",
            "data": {
                "server_id": self.server_id,
                "previous_snapshot": "snapshot_old.json",
                "current_snapshot": "snapshot_new.json",
                "added": [{"path": "/etc/a"}],
                "deleted": [{"path": "/etc/b"}],
                "modified": [{"path": "/etc/c"}],
                "summary": {"added": 1, "deleted": 1, "modified": 1, "unchanged": 10},
            }
        }]

        app_diff = {
            "status": "changes_detected",
            "category": "app",
            "added_apps": [{"name": "app2"}],
            "removed_apps": [],
            "updated_apps": [{"name": "app1"}],
        }

        network_diff = {
            "status": "changes_detected",
            "category": "network",
            "modified_settings": {
                "ip_forward": {"old": "0", "new": "1", "section": "sysctl"},
                "hostname": {"old": "hostA", "new": "hostB", "section": "system"}
            }
        }

        # file_changes = 3, app_changes = 2, net_changes = 2 -> total = 7
        td = _compute_threshold_data(
            entries, threshold=5, approvals_dir=self.approvals_dir,
            server_id=self.server_id, network_diff=network_diff, app_diff=app_diff
        )

        basename = "report_test-srv-02_2026_09_07_12_00.json"
        meta = td["reports"][basename]
        self.assertEqual(meta["file_changes"], 3)
        self.assertEqual(meta["app_changes"], 2)
        self.assertEqual(meta["network_changes"], 2)
        self.assertEqual(meta["change_count"], 7)
        self.assertTrue(meta["threshold_exceeded"])

    def test_dashboard_html_contains_badges_and_sections(self):
        """Verify generated dashboard HTML contains numeric badge placeholders, app/net drift sections, and audit containers."""
        entries = [{
            "file": os.path.join(self.test_dir, "report_test-srv-02_2026_09_07_12_00.json"),
            "label": "Report 1",
            "data": {
                "server_id": self.server_id,
                "previous_snapshot": "snapshot_old.json",
                "added": [], "deleted": [], "modified": []
            }
        }]

        html = build_dashboard_html(
            entries,
            title="Dashboard Test",
            threshold_data={"threshold": 0, "reports": {}},
            app_diff={"status": "changes_detected", "added_apps": ["/bin/test"]},
            network_diff={"status": "changes_detected", "modified_settings": {"foo": {}}}
        )

        # Tab badges
        self.assertIn('id="badge-reports"', html)
        self.assertIn('id="badge-app"', html)
        self.assertIn('id="badge-network"', html)

        # Drift report sub-sections
        self.assertIn('id="appDriftReportSection"', html)
        self.assertIn('id="networkDriftReportSection"', html)

        # Per-tab baseline approval containers
        self.assertIn('id="appAuditContent"', html)
        self.assertIn('id="netAuditContent"', html)


if __name__ == "__main__":
    unittest.main()
