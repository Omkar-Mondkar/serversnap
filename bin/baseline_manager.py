#!/usr/bin/env python3
"""
Baseline Manager - Manages Golden Copy (Approved) Baselines




Workflow:
  1. Collect New Snapshot
  2. Compare with Approved Baseline
  3. If Different → Mark as Pending Approval
  4. User Reviews Changes
  5. Approve → Save as New Baseline (Golden Copy)
  6. Reject → Keep Old Baseline




Golden Copy stored as:
  - /else/serversnap/baselines/baseline_<server_id>_<category>.json
"""






import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Tuple








class BaselineManager:
    """Manages approved baselines (golden copies) for each category."""
   
    def __init__(self, server_id: str, baseline_dir: str):
        """
        Initialize baseline manager.
       
        Args:
            server_id: Unique server identifier
            baseline_dir: Directory to store baseline snapshots
        """
        self.server_id = server_id
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
       
        self.categories = ["drift", "app", "network"]
   
    def _get_baseline_path(self, category: str) -> Path:
        """Get path for baseline file."""
        return self.baseline_dir / f"baseline_{self.server_id}_{category}.json"
   
    def _get_history_path(self, category: str) -> Path:
        """Get path for history file."""
        return self.baseline_dir / f"history_{self.server_id}_{category}.json"
   
    def load_baseline(self, category: str) -> Optional[Dict[str, Any]]:
        """Load current approved baseline for category."""
        path = self._get_baseline_path(category)
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading baseline {category}: {e}")
            return None
   
    def save_baseline(self, category: str, data: Dict[str, Any], reason: str = "approved") -> bool:
        """
        Save new approved baseline.
        
        Args:
            category: "drift", "app", or "network"
            data: Snapshot data to save as new baseline
            reason: Reason for update (e.g., "approved", "manual_override")
        
        Returns:
            True if successful
        """
        if category not in self.categories:
            print(f"Invalid category: {category}")
            return False
        
        baseline_path = self._get_baseline_path(category)
        
        # Add metadata
        baseline_with_meta = {
            "metadata": {
                "server_id": self.server_id,
                "category": category,
                "baseline_created_at": datetime.now().isoformat(),
                "reason": reason
            },
            "data": data
        }
        
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".baseline_{category}_", dir=self.baseline_dir
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(baseline_with_meta, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, baseline_path)

            # Record in history
            self._record_history(category, baseline_with_meta, "saved")
            return True
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            print(f"Error saving baseline {category}: {e}")
            return False
   
    def _record_history(self, category: str, data: Dict[str, Any], action: str) -> None:
        """Record baseline history for audit trail."""
        history_path = self._get_history_path(category)
        
        history = []
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        
        history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "category": category,
            "metadata": data.get("metadata", {})
        })
        
        # Keep last 50 entries
        history = history[-50:]
        
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=f".hist_{category}_", dir=self.baseline_dir
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, history_path)
        except Exception:
            pass
   
    def compare_with_baseline(self, category: str, new_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Compare new snapshot with approved baseline.
        
        Returns:
            (has_changes, diff_dict)
        """
        baseline = self.load_baseline(category)
        
        if baseline is None:
            # No baseline yet, everything is new
            return True, {"status": "no_baseline", "note": "First snapshot"}
        
        baseline_data = baseline.get("data", {})
        
        # Generate diff
        diff = self._generate_diff(category, baseline_data, new_data)
        
        if category == "drift":
            has_changes = bool(diff.get("added_files") or diff.get("removed_files") or diff.get("modified_files"))
        elif category == "app":
            has_changes = bool(diff.get("added_apps") or diff.get("removed_apps") or diff.get("updated_apps"))
        elif category == "network":
            has_changes = bool(diff.get("modified_settings"))
        else:
            has_changes = baseline_data != new_data
        
        if not has_changes:
            return False, {"status": "no_changes"}
        return True, diff

    def _extract_app_map(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract name/path mapping from app snapshot data supporting both legacy and current schemas."""
        apps: Dict[str, Any] = {}
        if not isinstance(data, dict):
            return apps
        
        # Legacy applications list
        for item in data.get("applications", []):
            if isinstance(item, dict):
                k = item.get("path") or item.get("name")
                if k:
                    apps[k] = item

        # Standard executables, scripts, symlinks
        for section in ("executables", "scripts", "symlinks"):
            for item in data.get(section, []):
                if isinstance(item, dict):
                    k = item.get("path") or item.get("name")
                    if k:
                        apps[k] = item
        return apps

    def _generate_diff(self, category: str, old_data: Dict, new_data: Dict) -> Dict[str, Any]:
        """Generate detailed diff between old and new."""
        diff = {
            "status": "changes_detected",
            "category": category,
            "timestamp": datetime.now().isoformat()
        }
        
        if category == "drift":
            diff["added_files"] = [k for k in new_data.keys() if k not in old_data]
            diff["removed_files"] = [k for k in old_data.keys() if k not in new_data]
            diff["modified_files"] = [
                k for k in old_data.keys()
                if k in new_data and old_data[k] != new_data[k]
            ]
        
        elif category == "app":
            old_apps = self._extract_app_map(old_data)
            new_apps = self._extract_app_map(new_data)
            
            diff["added_apps"] = [new_apps[n] for n in new_apps if n not in old_apps]
            diff["removed_apps"] = [old_apps[n] for n in old_apps if n not in new_apps]
            diff["updated_apps"] = []
            for n in old_apps:
                if n in new_apps:
                    old_item = old_apps[n]
                    new_item = new_apps[n]
                    if isinstance(old_item, dict) and isinstance(new_item, dict):
                        changes = []
                        if old_item.get("size") != new_item.get("size"):
                            changes.append(f"size: {old_item.get('size')} -> {new_item.get('size')}")
                        if old_item.get("permissions") != new_item.get("permissions"):
                            changes.append(f"permissions: {old_item.get('permissions')} -> {new_item.get('permissions')}")
                        if old_item.get("target") != new_item.get("target"):
                            changes.append(f"target: {old_item.get('target')} -> {new_item.get('target')}")
                        if old_item.get("subtype") != new_item.get("subtype"):
                            changes.append(f"subtype: {old_item.get('subtype')} -> {new_item.get('subtype')}")
                        if old_item.get("type") != new_item.get("type"):
                            changes.append(f"type: {old_item.get('type')} -> {new_item.get('type')}")
                        if changes:
                            diff["updated_apps"].append({
                                "name": new_item.get("name", n),
                                "path": n,
                                "old": old_item,
                                "new": new_item,
                                "changes": changes
                            })
                    elif old_item != new_item:
                        diff["updated_apps"].append({
                            "name": n,
                            "path": n,
                            "old": old_item,
                            "new": new_item,
                            "changes": ["value changed"]
                        })
       
        elif category == "network":
            diff["modified_settings"] = {}
            for sec_or_key, val in new_data.items():
                old_val = old_data.get(sec_or_key)
                if isinstance(val, dict) and isinstance(old_val, dict):
                    for sub_k, sub_v in val.items():
                        if sub_k in old_val and old_val[sub_k] != sub_v:
                            diff["modified_settings"][sub_k] = {
                                "old": old_val[sub_k],
                                "new": sub_v,
                                "section": sec_or_key,
                            }
                        elif sub_k not in old_val:
                            diff["modified_settings"][sub_k] = {
                                "old": None,
                                "new": sub_v,
                                "section": sec_or_key,
                            }
                    for sub_k in old_val:
                        if sub_k not in val:
                            diff["modified_settings"][sub_k] = {
                                "old": old_val[sub_k],
                                "new": None,
                                "section": sec_or_key,
                            }
                elif isinstance(val, dict) and old_val is None:
                    for sub_k, sub_v in val.items():
                        diff["modified_settings"][sub_k] = {
                            "old": None,
                            "new": sub_v,
                            "section": sec_or_key,
                        }
                else:
                    if sec_or_key in old_data and old_data[sec_or_key] != val:
                        diff["modified_settings"][sec_or_key] = {
                            "old": old_data[sec_or_key],
                            "new": val,
                        }
                    elif sec_or_key not in old_data:
                        diff["modified_settings"][sec_or_key] = {
                            "old": None,
                            "new": val,
                        }
            for old_k, old_v in old_data.items():
                if old_k not in new_data and not isinstance(old_v, dict):
                    diff["modified_settings"][old_k] = {
                        "old": old_v,
                        "new": None,
                    }
       
        return diff
   
    def get_all_baselines(self) -> Dict[str, Dict[str, Any]]:
        """Get all current baselines."""
        baselines = {}
        for category in self.categories:
            baseline = self.load_baseline(category)
            if baseline:
                baselines[category] = baseline.get("metadata", {})
        return baselines
   
    def get_baseline_status_summary(self) -> Dict[str, Any]:
        """Get summary of all baselines."""
        summary = {
            "server_id": self.server_id,
            "checked_at": datetime.now().isoformat(),
            "baselines": {}
        }
       
        for category in self.categories:
            baseline = self.load_baseline(category)
            if baseline:
                meta = baseline.get("metadata", {})
                summary["baselines"][category] = {
                    "status": "exists",
                    "created_at": meta.get("baseline_created_at"),
                    "reason": meta.get("reason")
                }
            else:
                summary["baselines"][category] = {"status": "not_created"}
       
        return summary
   
    def initialize_all_baselines(self, snapshots: Dict[str, Dict[str, Any]]) -> None:
        """Initialize all baselines from snapshots (first run)."""
        for category, data in snapshots.items():
            if category in self.categories:
                self.save_baseline(category, data, reason="initial_baseline")


    # ------------------------------------------------------------------
    # Golden Snapshot (single source of truth for approved state)
    # ------------------------------------------------------------------


    def _get_golden_path(self) -> Path:
        """Path to the golden snapshot JSON file."""
        return self.baseline_dir / f"golden_{self.server_id}.json"


    def load_golden_snapshot(self) -> Optional[Dict[str, Any]]:
        """Load the current approved golden snapshot.


        Returns the raw report dict on success, or None if it doesn't exist yet.
        """
        path = self._get_golden_path()
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: Could not load golden snapshot: {exc}")
            return None


    def save_golden_snapshot(self, report_data: Dict[str, Any], report_label: str = "") -> bool:
        """Save a new golden snapshot (called when a report is approved).


        The golden snapshot wraps the raw report JSON with approval metadata.


        Args:
            report_data: The full raw report dict from the approved report file.
            report_label: Human-readable label for the approved report.


        Returns:
            True on success.
        """
        path = self._get_golden_path()
        payload = {
            "_golden_metadata": {
                "server_id": self.server_id,
                "approved_at": datetime.now().isoformat(),
                "report_label": report_label,
            },
            "report": report_data,
        }
        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".golden_", dir=self.baseline_dir
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
            print(f"✅ Golden snapshot updated: {path}")
            return True
        except Exception as exc:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            print(f"❌ Failed to save golden snapshot: {exc}")
            return False


if __name__ == "__main__":
    # Example usage
    manager = BaselineManager("web01", "/else/serversnap/baselines")
   
    # Initialize with sample data
    sample_snapshots = {
        "drift": {"file1": "hash1", "file2": "hash2"},
        "app": {"applications": [{"name": "bash", "version": "5.1.8"}]},
        "network": {"tcp_fin_timeout": "60", "tcp_tw_reuse": "2"}
    }
   
    manager.initialize_all_baselines(sample_snapshots)
   
    # Load and check
    baselines = manager.get_all_baselines()
    print(f"Baselines: {baselines}")
   
    # Check for changes
    new_snapshot = {
        "drift": {"file1": "hash1", "file2": "hash3"},  # file2 changed
        "app": {"applications": [{"name": "bash", "version": "5.1.16"}]},  # version changed
        "network": {"tcp_fin_timeout": "30", "tcp_tw_reuse": "2"}  # timeout changed
    }
   
    for category, data in new_snapshot.items():
        has_changes, diff = manager.compare_with_baseline(category, data)
        print(f"\n{category}: {has_changes}")
        print(f"  Diff: {diff}")



