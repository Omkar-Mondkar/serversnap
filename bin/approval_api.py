#!/usr/bin/env python3
"""
Approval API Handler - REST endpoints for change approval




Handles approval requests from dashboard UI via HTTP API calls.
"""




import json
from pathlib import Path
from typing import Dict, Any, Tuple
from datetime import datetime








class ApprovalAPIHandler:
    """Handles approval API requests from dashboard."""
   
    def __init__(self, server_id: str, approval_dir: str, baseline_dir: str):
        """
        Initialize approval API handler.
       
        Args:
            server_id: Server identifier
            approval_dir: Directory with approval records
            baseline_dir: Directory with baseline snapshots
        """
        self.server_id = server_id
        self.approval_dir = Path(approval_dir)
        self.baseline_dir = Path(baseline_dir)
       
        self.approval_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
       
        self.pending_file = self.approval_dir / f"pending_{server_id}.json"
        self.responses_file = self.approval_dir / f"responses_{server_id}.json"
   
    def approve_changes(self, category: str, snapshot_data: Dict[str, Any], user: str = "dashboard_user", reason: str = "user_approved") -> Tuple[bool, str]:
        """
        Approve pending changes and save as new baseline.
        
        Args:
            category: "drift", "app", or "network"
            snapshot_data: Current snapshot data to save as baseline
            user: User name of approver
            reason: Ticket or reason for approval
        
        Returns:
            (success, message)
        """
        try:
            # Update baseline
            from baseline_manager import BaselineManager
            manager = BaselineManager(self.server_id, str(self.baseline_dir))
            manager.save_baseline(category, snapshot_data, reason=reason or "user_approved")
            
            # Record approval response
            self._record_response(category, "approved", snapshot_data, user=user, reason=reason)
            
            # Update pending status
            self._update_pending_status(category, "approved")
            
            return True, f"✅ {category} changes approved and saved as baseline"
        
        except Exception as e:
            return False, f"❌ Error approving {category}: {str(e)}"
    
    def reject_changes(self, category: str, user: str = "dashboard_user", reason: str = "user_rejected") -> Tuple[bool, str]:
        """
        Reject pending changes (revert to previous baseline).
        
        Args:
            category: "drift", "app", or "network"
            user: User name
            reason: Ticket or reason for rejection
        
        Returns:
            (success, message)
        """
        try:
            # Load previous baseline (no action needed, just mark as rejected)
            # The system will continue using the old baseline
            
            # Record rejection
            self._record_response(category, "rejected", {}, user=user, reason=reason)
            
            # Update pending status
            self._update_pending_status(category, "rejected")
            
            return True, f"❌ {category} changes rejected. Previous baseline remains active."
        
        except Exception as e:
            return False, f"Error rejecting {category}: {str(e)}"
    
    def _update_pending_status(self, category: str, status: str) -> None:
        """Update pending changes file with new status."""
        pending = self._load_json(self.pending_file)
        
        if category not in pending:
            pending[category] = {}
        pending[category]["status"] = status
        pending[category]["response_at"] = datetime.now().isoformat()
      
        self._save_json(self.pending_file, pending)

    def _record_response(self, category: str, action: str, data: Dict[str, Any], user: str = "dashboard_user", reason: str = "") -> None:
        """Record approval/rejection response."""
        responses = self._load_json(self.responses_file)
        
        if "responses" not in responses:
            responses["responses"] = []
        
        responses["responses"].append({
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "action": action,
            "server_id": self.server_id,
            "user": user or "dashboard_user",
            "reason": reason or "",
        })
        
        # Keep last 100
        responses["responses"] = responses["responses"][-100:]
        
        self._save_json(self.responses_file, responses)

    def _load_json(self, filepath: Path) -> Dict[str, Any]:
        """Load JSON file."""
        try:
            if filepath.exists():
                with open(filepath, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_json(self, filepath: Path, data: Dict[str, Any]) -> None:
        """Save JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_approval_status(self) -> Dict[str, Any]:
        """Get current approval status for all categories."""
        pending = self._load_json(self.pending_file)
        
        status = {
            "server_id": self.server_id,
            "checked_at": datetime.now().isoformat(),
            "categories": {}
        }
        
        for category in ["drift", "app", "network"]:
            if category in pending and pending[category].get("status") == "pending":
                category_data = pending[category]
                changes_data = category_data.get("changes", {})
                
                if isinstance(changes_data, dict):
                    change_count = len(changes_data)
                elif isinstance(changes_data, list):
                    change_count = len(changes_data)
                else:
                    change_count = 1 if changes_data else 0
                
                status["categories"][category] = {
                    "status": "pending",
                    "changes": change_count,
                    "timestamp": category_data.get("timestamp"),
                    "created_at": category_data.get("created_at")
                }
            elif category in pending and pending[category].get("status") in ("approved", "rejected"):
                category_data = pending[category]
                status["categories"][category] = {
                    "status": category_data.get("status"),
                    "changes": 0,
                    "timestamp": category_data.get("response_at") or category_data.get("timestamp"),
                }
            else:
                # No pending changes for this category
                status["categories"][category] = {
                    "status": "no_changes",
                    "changes": 0
                }
       
        return status
   
    def get_approval_history(self, limit: int = 20) -> Dict[str, Any]:
        """Get approval decision history."""
        responses = self._load_json(self.responses_file)
        history = responses.get("responses", [])
       
        return {
            "server_id": self.server_id,
            "total_decisions": len(history),
            "recent": history[-limit:]
        }








def handle_approval_request(request_data: Dict[str, Any], handler: ApprovalAPIHandler) -> Dict[str, Any]:
    """
    Handle approval API request from dashboard.
   
    Request format:
    {
        "action": "approve" | "reject",
        "category": "drift" | "app" | "network",
        "snapshot_data": {...}  # Required for approve
    }
    Response format:
    {
        "success": bool,
        "message": str,
        "status": current_status_dict
    }
    """
    action = request_data.get("action")
    category = request_data.get("category")
    snapshot_data = request_data.get("snapshot_data", {})
   
    response = {
        "timestamp": datetime.now().isoformat(),
        "action_requested": action,
        "category": category
    }
   
    if action == "approve":
        success, message = handler.approve_changes(category, snapshot_data)
        response["success"] = success
        response["message"] = message
   
    elif action == "reject":
        success, message = handler.reject_changes(category)
        response["success"] = success
        response["message"] = message
   
    else:
        response["success"] = False
        response["message"] = f"Unknown action: {action}"
   
    # Include current status
    response["status"] = handler.get_approval_status()
   
    return response








if __name__ == "__main__":
    # Example usage
    handler = ApprovalAPIHandler("web01", "/else/serversnap/approvals", "/else/serversnap/baselines")
   
    # Simulate approve request
    approve_request = {
        "action": "approve",
        "category": "app",
        "snapshot_data": {
            "applications": [
                {"name": "bash", "version": "5.1.16"},
                {"name": "python", "version": "3.9.0"}
            ]
        }
    }
   
    result = handle_approval_request(approve_request, handler)
    print(f"Approve result: {json.dumps(result, indent=2)}")
   
    # Simulate reject request
    reject_request = {
        "action": "reject",
        "category": "network"
    }
   
    result = handle_approval_request(reject_request, handler)
    print(f"\nReject result: {json.dumps(result, indent=2)}")
   
    # Show status
    status = handler.get_approval_status()
    print(f"\nApproval status: {json.dumps(status, indent=2)}")

