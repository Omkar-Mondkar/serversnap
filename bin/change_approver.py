#!/usr/bin/env python3
"""
Change Approval System for Snapshots


Manages approval of changes across 3 categories:
1. Configuration Drift (file/directory changes)
2. Application Snapshots (binary inventory changes)
3. Network Settings (system configuration changes)


Usage:
    approver = ChangeApprover(server_id, approval_dir)
   
    # Check if changes pending approval
    pending = approver.get_pending_changes()
    if pending:
        print("Changes pending approval:")
        for category, changes in pending.items():
            print(f"  {category}: {len(changes)} changes")
   
    # Approve changes
    approver.approve_changes(category="all", timestamp=current_timestamp)
   
    # Reject changes (revert to previous baseline)
    approver.reject_changes(category="app")
"""


import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional




class ChangeApprover:
    """Manages change approval workflow for snapshots."""
   
    def __init__(self, server_id: str, approval_dir: str):
        """
        Initialize change approver.
       
        Args:
            server_id: Unique server identifier
            approval_dir: Directory to store approval records
        """
        self.server_id = server_id
        self.approval_dir = Path(approval_dir)
        self.approval_dir.mkdir(parents=True, exist_ok=True)
       
        self.approval_file = self.approval_dir / f"approvals_{server_id}.json"
        self.pending_file = self.approval_dir / f"pending_{server_id}.json"
       
        # Ensure files exist
        for f in [self.approval_file, self.pending_file]:
            if not f.exists():
                with open(f, 'w') as fp:
                    json.dump({}, fp, indent=2)
   
    def _load_json(self, filepath: Path) -> Dict[str, Any]:
        """Load JSON file safely."""
        try:
            if filepath.exists():
                with open(filepath, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
   
    def _save_json(self, filepath: Path, data: Dict[str, Any]) -> None:
        """Save JSON file safely."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save {filepath}: {e}")
   
    def record_pending_changes(self, category: str, changes: Dict[str, Any], timestamp: str) -> None:
        """
        Record pending changes for approval.
       
        Args:
            category: "drift", "app", or "network"
            changes: Dictionary of changes detected
            timestamp: ISO timestamp of snapshot
        """
        pending = self._load_json(self.pending_file)
       
        pending[category] = {
            "timestamp": timestamp,
            "changes": changes,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
       
        self._save_json(self.pending_file, pending)
        print(f"📋 Recorded pending changes for {category}: {len(changes)} items")
   
    def get_pending_changes(self) -> Dict[str, Any]:
        """Get all pending changes awaiting approval."""
        pending = self._load_json(self.pending_file)
        return {
            cat: data for cat, data in pending.items()
            if data.get("status") == "pending"
        }
   
    def approve_changes(self, category: Optional[str] = None, timestamp: Optional[str] = None) -> bool:
        """
        Approve pending changes.
       
        Args:
            category: Specific category ("drift", "app", "network") or None for all
            timestamp: Timestamp to approve (or latest if None)
       
        Returns:
            True if approval successful
        """
        pending = self._load_json(self.pending_file)
        approvals = self._load_json(self.approval_file)
       
        if category:
            categories_to_approve = [category]
        else:
            categories_to_approve = list(pending.keys())
       
        approved_count = 0
        for cat in categories_to_approve:
            if cat in pending and pending[cat].get("status") == "pending":
                change_data = pending[cat]
               
                # Record approval
                if "approvals" not in approvals:
                    approvals["approvals"] = []
               
                approvals["approvals"].append({
                    "category": cat,
                    "timestamp": change_data.get("timestamp"),
                    "approved_at": datetime.now().isoformat(),
                    "changes_count": len(change_data.get("changes", {}))
                })
               
                # Mark as approved
                pending[cat]["status"] = "approved"
                pending[cat]["approved_at"] = datetime.now().isoformat()
                approved_count += 1
               
                print(f"✅ Approved changes for {cat}")
       
        self._save_json(self.pending_file, pending)
        self._save_json(self.approval_file, approvals)
       
        return approved_count > 0
   
    def reject_changes(self, category: Optional[str] = None) -> bool:
        """
        Reject pending changes (revert to previous baseline).
       
        Args:
            category: Specific category or None for all
       
        Returns:
            True if rejection successful
        """
        pending = self._load_json(self.pending_file)
       
        if category:
            categories_to_reject = [category]
        else:
            categories_to_reject = list(pending.keys())
       
        rejected_count = 0
        for cat in categories_to_reject:
            if cat in pending and pending[cat].get("status") == "pending":
                pending[cat]["status"] = "rejected"
                pending[cat]["rejected_at"] = datetime.now().isoformat()
                rejected_count += 1
                print(f"❌ Rejected changes for {cat}")
       
        self._save_json(self.pending_file, pending)
        return rejected_count > 0
   
    def get_approval_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get approval history."""
        approvals = self._load_json(self.approval_file)
        history = approvals.get("approvals", [])
        return history[-limit:]
   
    def get_change_summary(self) -> Dict[str, Any]:
        """Get summary of pending vs approved changes."""
        pending = self._load_json(self.pending_file)
        approvals = self._load_json(self.approval_file)
       
        summary = {
            "pending": {},
            "approved": {},
            "rejected": {}
        }
       
        for cat, data in pending.items():
            status = data.get("status", "unknown")
            if status not in summary:
                summary[status] = {}
           
            summary[status][cat] = {
                "timestamp": data.get("timestamp"),
                "changes_count": len(data.get("changes", {})),
                "created_at": data.get("created_at")
            }
       
        summary["total_approvals"] = len(approvals.get("approvals", []))
       
        return summary
   
    def generate_approval_html(self) -> str:
        """Generate HTML showing pending approvals for dashboard."""
        pending = self.get_pending_changes()
        summary = self.get_change_summary()
       
        if not pending:
            return """
            <div class="approval-panel">
                <h3>✅ All Changes Approved</h3>
                <p>No pending changes awaiting approval.</p>
            </div>
            """
       
        html = '<div class="approval-panel">'
        html += '<h3>⏳ Pending Approval</h3>'
        html += '<table class="approval-table">'
        html += '<tr><th>Category</th><th>Changes</th><th>Status</th><th>Action</th></tr>'
       
        for cat, data in pending.items():
            changes_count = len(data.get("changes", {}))
            html += f"""
            <tr>
                <td>{cat.upper()}</td>
                <td>{changes_count} changes</td>
                <td><span class="badge pending">Pending</span></td>
                <td>
                    <button onclick="approveChanges('{cat}')" class="btn-approve">Approve</button>
                    <button onclick="rejectChanges('{cat}')" class="btn-reject">Reject</button>
                </td>
            </tr>
            """
       
        html += '</table></div>'
        return html




def generate_change_diff(old_data: Dict, new_data: Dict) -> Dict[str, List[Dict]]:
    """
    Generate diff between old and new snapshots.
   
    Returns dict with 'added', 'removed', 'modified' keys.
    """
    diff = {
        "added": [],
        "removed": [],
        "modified": []
    }
   
    old_keys = set(old_data.keys()) if old_data else set()
    new_keys = set(new_data.keys()) if new_data else set()
   
    # Added items
    for key in new_keys - old_keys:
        diff["added"].append({
            "key": key,
            "new_value": new_data[key]
        })
   
    # Removed items
    for key in old_keys - new_keys:
        diff["removed"].append({
            "key": key,
            "old_value": old_data[key]
        })
   
    # Modified items
    for key in old_keys & new_keys:
        if old_data[key] != new_data[key]:
            diff["modified"].append({
                "key": key,
                "old_value": old_data[key],
                "new_value": new_data[key]
            })
   
    return diff




if __name__ == "__main__":
    # Example usage
    approver = ChangeApprover("web01", "/else/serversnap/approvals")
   
    # Record some pending changes
    test_changes = {
        "bash": {"old": "5.1.8", "new": "5.1.16"},
        "systemd": {"old": "249.1", "new": "250.0"}
    }
   
    approver.record_pending_changes("app", test_changes, datetime.now().isoformat())
   
    # Show pending
    pending = approver.get_pending_changes()
    print(f"\nPending changes: {pending}")
   
    # Show summary
    summary = approver.get_change_summary()
    print(f"\nChange summary: {summary}")
   
    # Approve
    approver.approve_changes("app")
   
    # Show history
    history = approver.get_approval_history()
    print(f"\nApproval history: {history}")



