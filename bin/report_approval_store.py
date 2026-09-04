#!/usr/bin/env python3
"""
report_approval_store.py
========================


Per-report approval state store.


Tracks the approval status of every drift report file individually, keyed by
the report's basename (e.g. "report_web01_2026_07_29_09_54_16.json").


State file location:
    <approvals_dir>/report_approvals_<server_id>.json


Schema:
{
  "<report_basename>": {
    "status":            "pending" | "approved" | "rejected",
    "report_label":      "<human label from visualize_report.py>",
    "change_count":      <int>,        # added + deleted + modified
    "threshold":         <int>,        # threshold in effect when registered
    "threshold_exceeded": <bool>,
    "created_at":        "<ISO>",
    "decided_at":        "<ISO> | null",
    "description":       "<free-text reason entered by the approver, or \"\">"
  },
  ...
}
"""


from __future__ import annotations


import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional




class ReportApprovalStore:
    """Per-report approval state, persisted as a single JSON file."""


    def __init__(self, server_id: str, approvals_dir: str) -> None:
        self.server_id = server_id
        self.approvals_dir = Path(approvals_dir)
        self.approvals_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self.approvals_dir / f"report_approvals_{server_id}.json"


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    def _load(self) -> Dict[str, Any]:
        try:
            if self._store_path.exists():
                with open(self._store_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        return {}


    def _save(self, data: Dict[str, Any]) -> None:
        """Atomic write via temp file + os.replace."""
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".report_approvals_", dir=self.approvals_dir
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self._store_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------


    def get_all(self) -> Dict[str, Any]:
        """Return the full store dict (keyed by report basename)."""
        return self._load()


    def set_pending(
        self,
        report_basename: str,
        label: str,
        change_count: int,
        threshold: int,
    ) -> None:
        """Register a report as pending (only if not already decided).




        If the report already has a status of 'approved' or 'rejected' this
        call is a no-op — we never downgrade a decision.
        """
        data = self._load()
        existing = data.get(report_basename, {})
        if existing.get("status") in ("approved", "rejected"):
            return  # decision already made — preserve it


        data[report_basename] = {
            "status": "pending",
            "report_label": label,
            "change_count": change_count,
            "threshold": threshold,
            "threshold_exceeded": change_count > threshold,
            "created_at": existing.get("created_at") or self._now(),
            "decided_at": None,
            "description": existing.get("description", ""),
        }
        self._save(data)


    def approve(self, report_basename: str, description: str = "") -> bool:
        """Mark a report as approved. Returns True on success.


        ``description`` is an optional free-text reason entered by the
        approver (e.g. "planned patch window"), stored alongside the
        decision date so the audit trail shows *when* and *why*.
        """
        data = self._load()
        if report_basename not in data:
            return False
        data[report_basename]["status"] = "approved"
        data[report_basename]["decided_at"] = self._now()
        data[report_basename]["description"] = description.strip()
        self._save(data)
        return True


    def reject(self, report_basename: str, description: str = "") -> bool:
        """Mark a report as rejected. Returns True on success.


        ``description`` is an optional free-text reason entered by the
        approver, stored alongside the decision date.
        """
        data = self._load()
        if report_basename not in data:
            return False
        data[report_basename]["status"] = "rejected"
        data[report_basename]["decided_at"] = self._now()
        data[report_basename]["description"] = description.strip()
        self._save(data)
        return True


    def get_status_summary(self) -> Dict[str, Any]:
        """Return a summary dict ready to be serialised as /api/report-status."""
        data = self._load()
        return {
            "server_id": self.server_id,
            "checked_at": self._now(),
            "reports": data,
        }


    def get_record(self, report_basename: str) -> Optional[Dict[str, Any]]:
        """Return the record for one report, or None if unknown."""
        return self._load().get(report_basename)



