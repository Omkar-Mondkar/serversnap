#!/usr/bin/env python3
"""
test_baseline_auto_approval.py
==============================

Unit and integration tests verifying:
1. First snapshot run automatically approves the initial baseline.
2. Baseline JSON, AuditStore, ReportApprovalStore, and BaselineManager are updated.
3. Second snapshot run without changes returns 0 changes.
4. Subsequent modifications are accurately detected and compared against baseline.
5. Dashboard visualization assigns 'approved' status to the initial baseline run.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add bin to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit_store import AuditStore
from report_approval_store import ReportApprovalStore
from baseline_manager import BaselineManager
from server_snapshot import load_config
from visualize_report import _compute_threshold_data, build_dashboard_html


class TestBaselineAutoApproval(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="serversnap_test_")
        self.tracked_dir = os.path.join(self.test_dir, "tracked")
        self.snapshot_dir = os.path.join(self.test_dir, "snapshots")
        self.report_dir = os.path.join(self.test_dir, "reports")
        self.baseline_dir = os.path.join(self.test_dir, "baseline")
        self.baselines_dir = os.path.join(self.test_dir, "baselines")
        self.approvals_dir = os.path.join(self.test_dir, "approvals")

        os.makedirs(self.tracked_dir, exist_ok=True)
        os.makedirs(self.snapshot_dir, exist_ok=True)
        os.makedirs(self.report_dir, exist_ok=True)

        # Create sample files
        self.file1 = os.path.join(self.tracked_dir, "app.conf")
        with open(self.file1, "w") as f:
            f.write("port=8080\n")

        self.file2 = os.path.join(self.tracked_dir, "settings.json")
        with open(self.file2, "w") as f:
            f.write('{"debug": true}\n')

        self.config_data = {
            "server_id": "test-srv-01",
            "hostname": "test-host",
            "snapshot_dir": self.snapshot_dir,
            "report_dir": self.report_dir,
            "paths": [
                {
                    "path": self.tracked_dir,
                    "recursive": True,
                    "include_content": True,
                }
            ],
            "change_threshold": 10,
            "retention_count": 5,
        }
        self.config_path = os.path.join(self.test_dir, "config.json")
        with open(self.config_path, "w") as f:
            json.dump(self.config_data, f)

        self.config = load_config(self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_snapshot_step(self):
        """Execute a full server_snapshot step with the current environment."""
        import server_snapshot
        old_argv = sys.argv
        sys.argv = ["server_snapshot.py", "--config", self.config_path, "--no-alert"]
        try:
            return server_snapshot.main()
        finally:
            sys.argv = old_argv

    def test_first_run_auto_approves_baseline(self):
        """Verify that the first run auto-creates and approves baseline."""
        exit_code = self._run_snapshot_step()
        self.assertEqual(exit_code, 0, "First run should exit with code 0 (auto-approved initial baseline)")

        # 1. Baseline file must exist
        baseline_file = os.path.join(self.baseline_dir, f"baseline_{self.config.server_id}.json")
        self.assertTrue(os.path.isfile(baseline_file), "Baseline file was not created on first run")

        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline_data = json.load(f)
        self.assertIn("entries", baseline_data)
        # Directory + 2 files = 3 entries
        self.assertEqual(len(baseline_data["entries"]), 3)

        # 2. AuditStore must record APPROVED decision
        audit_store = AuditStore(self.snapshot_dir, self.config.server_id)
        history = audit_store.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "APPROVED")
        self.assertIn("system", history[0]["user"])
        self.assertIn("Auto-approved", history[0]["reason"])

        # 3. ReportApprovalStore must record report as approved
        rep_store = ReportApprovalStore(self.config.server_id, self.approvals_dir)
        reports = rep_store.get_all()
        self.assertEqual(len(reports), 1)
        rep_key = list(reports.keys())[0]
        self.assertEqual(reports[rep_key]["status"], "approved")

    def test_second_run_no_changes(self):
        """Verify second run against auto-approved baseline produces 0 changes."""
        self._run_snapshot_step()
        time.sleep(1.1)  # Ensure unique timestamp for second report

        # Second run without modifying files
        exit_code = self._run_snapshot_step()
        self.assertEqual(exit_code, 0, "Second run with no changes should exit with 0")

        report_files = sorted(Path(self.report_dir).glob(f"report_{self.config.server_id}_*.json"))
        self.assertEqual(len(report_files), 2)
        with open(report_files[-1], "r", encoding="utf-8") as f:
            latest_rep = json.load(f)

        self.assertEqual(latest_rep["summary"]["added"], 0)
        self.assertEqual(latest_rep["summary"]["deleted"], 0)
        self.assertEqual(latest_rep["summary"]["modified"], 0)
        self.assertEqual(latest_rep["summary"]["unchanged"], 3)

    def test_subsequent_run_detects_modification(self):
        """Verify modifications after first run are accurately detected against baseline."""
        self._run_snapshot_step()
        time.sleep(1.1)

        # Modify app.conf
        with open(self.file1, "w") as f:
            f.write("port=9090\n# updated\n")

        # Add a new file
        file3 = os.path.join(self.tracked_dir, "extra.txt")
        with open(file3, "w") as f:
            f.write("extra file content\n")

        exit_code = self._run_snapshot_step()
        self.assertEqual(exit_code, 1, "Run with modifications should exit with 1 (changes detected)")

        report_files = sorted(Path(self.report_dir).glob(f"report_{self.config.server_id}_*.json"))
        self.assertEqual(len(report_files), 2)
        with open(report_files[-1], "r", encoding="utf-8") as f:
            latest_rep = json.load(f)

        # app.conf modified (+ dir mtime modified)
        self.assertGreaterEqual(latest_rep["summary"]["modified"], 1)
        self.assertEqual(latest_rep["summary"]["added"], 1)
        self.assertEqual(latest_rep["summary"]["deleted"], 0)

        # Check modified file detail includes app.conf
        mod_paths = [m["path"] for m in latest_rep["modified"]]
        self.assertTrue(any("app.conf" in p for p in mod_paths))

    def test_visualize_threshold_data_baseline_auto_approved(self):
        """Verify _compute_threshold_data marks baseline run as approved and not exceeded."""
        self._run_snapshot_step()

        report_files = sorted(Path(self.report_dir).glob(f"report_{self.config.server_id}_*.json"))
        self.assertEqual(len(report_files), 1)
        with open(report_files[0], "r", encoding="utf-8") as f:
            rep_data = json.load(f)

        entries = [{"file": str(report_files[0]), "label": "Initial Run", "data": rep_data}]
        threshold_data = _compute_threshold_data(entries, 1, self.approvals_dir, self.config.server_id)

        rep_basename = os.path.basename(str(report_files[0]))
        r_meta = threshold_data["reports"][rep_basename]
        self.assertEqual(r_meta["status"], "approved")
        self.assertFalse(r_meta["threshold_exceeded"])

        # Render dashboard HTML without errors
        html = build_dashboard_html(entries, "Test Dashboard", threshold_data=threshold_data)
        self.assertIn("test-srv-01", html)
        self.assertIn("threshold-data", html)


if __name__ == "__main__":
    unittest.main()
