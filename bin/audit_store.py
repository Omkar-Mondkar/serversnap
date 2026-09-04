"""Persistent approved baseline and append-only audit decision storage."""


from __future__ import annotations


import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from server_snapshot import load_snapshot_file




class AuditStore:
    def __init__(self, snapshot_dir: str, server_id: str) -> None:
        self.root = Path(snapshot_dir).parent
        self.baseline_dir = self.root / "baseline"
        self.baseline_path = self.baseline_dir / f"baseline_{server_id}.json"
        self.history_path = self.root / "history.json"
        self.audit_path = self.root / "audit.log"
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.baseline_dir, 0o700)
        except OSError:
            pass


    def load_baseline(self) -> Optional[Dict[str, Any]]:
        return load_snapshot_file(str(self.baseline_path)) if self.baseline_path.is_file() else None


    def promote(self, snapshot_path: str) -> None:
        temporary = self.baseline_path.with_suffix(".tmp")
        shutil.copyfile(snapshot_path, temporary)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.baseline_path)


    def append(self, action: str, snapshot_path: str, user: str, reason: str) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "snapshot_id": Path(snapshot_path).name,
            "user": user,
            "reason": reason,
        }
        history: List[Dict[str, str]] = []
        if self.history_path.is_file():
            try:
                history = json.loads(self.history_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        history.append(record)
        temporary = self.history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.history_path)
        with self.audit_path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(record, sort_keys=True) + "\n")


    def history(self) -> List[Dict[str, str]]:
        if not self.history_path.is_file():
            return []
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

