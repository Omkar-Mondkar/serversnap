---
name: Passive_User
description: >-
  Enforces non-invasive, strictly read-only monitoring on Linux servers.
  Ensures no part of the code ever executes mutating writes as root to system
  configuration or host targets. Restricts all file writes to designated application directories.
---

# Passive_User Skill — Read-Only Linux Server Monitoring Doctrine

The **Passive_User** skill defines the fundamental operational and security doctrine for ServerSnap when deployed onto Linux servers (production, staging, and multi-tenant environments).

---

## 🎯 Core Doctrine & Purpose

ServerSnap is designed as a **strictly passive, non-invasive observer**. Its sole mission is to detect configuration drift, record system state, and visualize baseline changes.

> [!CAUTION]
> **ABSOLUTE RULE: ZERO WRITES TO MONITORED SYSTEM TARGETS**
> Even if ServerSnap runs as the `root` user (or with `sudo` capabilities to read sensitive files like `/etc/shadow`, `/etc/ssh/sshd_config`, or query `iptables`), **NO PART OF THE CODE MUST EVER MODIFY, DELETE, OVERWRITE, OR WRITE TO ANY OS CONFIGURATION OR SYSTEM DIRECTORY.**

---

## ⚖️ Allowed vs. Prohibited Operations

| Category | Allowed Operations (✅ PASSIVE) | Prohibited Operations (❌ STRICTLY FORBIDDEN) |
| :--- | :--- | :--- |
| **System Files** | • Reading file content (`open(..., 'r')`, `cat`)<br>• Reading metadata (`stat`, permissions, owner, mtime)<br>• Calculating SHA-256 hashes (`hashlib.sha256`) | • Editing/writing to `/etc/*`, `/boot/*`, `/usr/*`<br>• Modifying system files (`open(..., 'w')`, `sed -i`, `echo >`)<br>• Changing file permissions or ownership (`chmod`, `chown`)<br>• Deleting monitored files (`unlink`, `rm`) |
| **Kernel & Sysctl** | • Reading active sysctl parameters (`sysctl -n <key>`)<br>• Inspecting `/proc/cmdline`, `/proc/sys/*`, `/proc/cpuinfo`<br>• Reading CPU governor `/sys/devices/system/cpu/...` | • Modifying kernel parameters (`sysctl -w <key>=<val>`)<br>• Writing to `/proc/sys/*` or `/sys/*`<br>• Altering CPU frequency or governor settings |
| **Network & Firewall** | • Inspecting sockets (`ss -tulpn`, `ss -s`)<br>• Querying interfaces and routes (`ip a`, `ip route`)<br>• Dumping firewall rules (`iptables-save`, `nft list ruleset`) | • Adding/altering firewall rules (`iptables -A`, `nft add`)<br>• Modifying IP addresses or routes (`ip addr add`, `ip route add`)<br>• Restarting network interfaces (`ifdown`, `ip link set down`) |
| **Processes & Services**| • Reading process status (`ps aux`, `/proc/<pid>/status`)<br>• Reading service status (`systemctl is-active`) | • Killing or stopping processes (`kill`, `pkill`)<br>• Starting, stopping, or reloading services (`systemctl restart`, `service reload`) |
| **Application I/O** | • Writing snapshots to configured `snapshot_dir`<br>• Writing reports to configured `report_dir`<br>• Writing baselines to `baselines/` and `approvals/`<br>• Writing logs to configured `log_file` | • Writing temporary files to `/etc`, `/root`, `/usr`, `/var/lib`<br>• Creating files in unconfigured arbitrary host paths |

---

## 🔒 Security Guidelines for Code Implementation

### 1. Filesystem Access Patterns in Python
When opening files or scanning directories:
```python
# ✅ CORRECT: Explicit read-only mode with error handling
try:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(max_bytes)
except PermissionError:
    log.warning("Permission denied reading %s (skipping)", path)
except OSError as e:
    log.warning("Could not read %s: %s", path, e)

# ❌ FORBIDDEN: Any mutating open mode ('w', 'a', 'r+', 'w+') on monitored paths
with open(monitored_system_path, "w") as f:  # NEVER DO THIS!
    f.write(...)
```

### 2. Subprocess Command Execution in Python and Bash
When executing system probes:
```python
# ✅ CORRECT: Read-only inspection command with explicit argument lists (no shell injection)
cmd = ["sysctl", "-n", key]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

# ❌ FORBIDDEN: Mutating or dangerous shell commands
subprocess.run(f"sysctl -w {key}={val}", shell=True)  # FORBIDDEN
subprocess.run(f"rm -rf {target_path}", shell=True)   # FORBIDDEN
```

### 3. Graceful Handling of Unprivileged Execution
If ServerSnap is executed by a non-root passive user, it must degrade gracefully:
```bash
# ✅ CORRECT: Graceful fallback in shell scripts
IPTABLES_RULES=$(iptables-save 2>/dev/null || true)
if [[ -z "$IPTABLES_RULES" ]]; then
    # Log informational warning, DO NOT fail or prompt for sudo
    echo "  firewall: \"(unprivileged user - permission denied)\"" >> "$SNAPSHOT_FILE"
fi
```

### 4. Atomic Application Data Writes
All application writes must be strictly isolated to the application-owned storage directory:
```python
# ✅ CORRECT: Atomic write within application's own directory
import tempfile, os, json

def save_app_data(dest_file_path: str, data: dict):
    # Ensure parent directory exists within application root
    parent_dir = os.path.dirname(dest_file_path)
    os.makedirs(parent_dir, exist_ok=True)
    
    # Create temp file inside the SAME directory
    with tempfile.NamedTemporaryFile("w", dir=parent_dir, delete=False, encoding="utf-8") as tf:
        temp_name = tf.name
        json.dump(data, tf, indent=2)
        tf.flush()
        os.fsync(tf.fileno())
    
    # Set safe application permissions (owner read/write only)
    os.chmod(temp_name, 0o600)
    # Atomic rename
    os.replace(temp_name, dest_file_path)
```

---

## 📋 Code Review & Verification Checklist for AI Agents

Before adding or modifying any code in ServerSnap, run this mental audit:

- [ ] Does any new code path open a file with `'w'`, `'a'`, or `'+'` on a path outside `snapshot_dir`, `report_dir`, `baselines`, `approvals`, `central_data`, `Output`, or `logs`? (**MUST BE NO**)
- [ ] Does any shell command or subprocess contain modifying flags (`-w`, `--set`, `-A`, `-D`, `-F`, `install`, `remove`, `delete`, `restart`, `reload`)? (**MUST BE NO**)
- [ ] Are all system calls strictly read-only inspection (`stat`, `read`, `sysctl -n`, `ip -j addr`, `ss -tulpn`, `iptables-save`)? (**MUST BE YES**)
- [ ] If permission is denied on a protected system file, does the script log a clean warning and continue rather than halting or attempting privilege escalation? (**MUST BE YES**)
- [ ] Are temporary files strictly generated inside the application directory rather than `/tmp` or system folders? (**MUST BE YES**)
