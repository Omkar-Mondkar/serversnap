---
name: passive-user
description: >-
  Enforces non-invasive, strictly read-only monitoring on Linux servers.
  Ensures no part of the code ever executes mutating writes as root to system
  configuration or host targets. Restricts all file writes to designated application directories.
---

# Passive User Skill — Read-Only Linux Monitoring Doctrine

## 🎯 Core Directive
ServerSnap is a strictly passive, non-invasive observer. Even when executed with root/sudo privileges to read sensitive files (`/etc/shadow`, `/etc/ssh/sshd_config`) or query firewall rules (`iptables-save`), **NO CODE MAY EVER WRITE AS ROOT TO HOST SYSTEM TARGETS OR CONFIGURATIONS.**

## 🚫 Strictly Forbidden Operations
- Writing, mutating, appending, or deleting any file under `/etc`, `/boot`, `/usr`, `/var`, `/sys`, `/proc`.
- Executing modifying kernel commands (`sysctl -w`).
- Modifying firewall or routing rules (`iptables -A`, `iptables -F`, `ip route add`).
- Mutating system services (`systemctl restart`, `service reload`).
- Writing temporary files to arbitrary host directories.

## ✅ Allowed Passive Operations
- Reading file metadata (`stat`, permissions, owner, mtime).
- Reading file content for diff calculation.
- Querying read-only system tools (`sysctl -n`, `ip -j addr`, `ss -tulpn`, `iptables-save`).
- Atomic writes strictly restricted to application-owned storage (`snapshots/`, `reports/`, `baselines/`, `approvals/`, `central_data/`, `Output/`, `logs/`).
- Graceful degradation when unprivileged.
