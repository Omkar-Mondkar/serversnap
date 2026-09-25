#!/usr/bin/env python3
"""
collect_network_snapshot.py
===========================
Server Configuration & Network Settings Collector (Golden Baseline / Diff-Friendly).
Captures configuration state across 10 key categories for drift detection:
  1. OS & Kernel Metadata
  2. Sysctl & TCP Parameters
  3. CPU Isolation, Power (Governor / C-States) & Boot Params
  4. IRQ Affinity & irqbalance
  5. NIC Driver, Rings, Coalescing, Offloads
  6. Onload / Solarflare Acceleration Stack
  7. Hugepages & System Tuned Profile
  8. NTP / PTP Time Sync State
  9. Core Services & Configuration File Checksums
 10. File Modification & Binary Integrity Checks

Outputs both:
  - config-snapshot.yaml (backward-compatible format for visualize_report.py)
  - config-snapshot.json (clean structured JSON)
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _run_cmd(cmd: List[str], timeout: float = 3.0) -> str:
    """Safely run a command and return stripped stdout, or empty string on error."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def _read_file(path: str) -> str:
    """Safely read a text file and return stripped content, or empty string on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


def _file_md5(path: str) -> str:
    """Compute MD5 checksum of a file, or empty string on error."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def collect_os_metadata() -> Dict[str, str]:
    """1. OS & KERNEL METADATA"""
    meta: Dict[str, str] = {}
    os_release = _read_file("/etc/os-release")
    if os_release:
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                meta["os_version"] = line.split("=", 1)[1].strip('"').strip("'")
                break
    if "os_version" not in meta:
        meta["os_version"] = platform.platform()

    meta["kernel_release"] = platform.release() or _run_cmd(["uname", "-r"])
    return meta


def collect_sysctl_params() -> Dict[str, str]:
    """2. SYSCTL & TCP KEEPALIVE PARAMS"""
    sysctl_keys = [
        "kernel.sched_migration_cost_ns",
        "kernel.sched_latency_ns",
        "kernel.sched_min_granularity_ns",
        "kernel.sched_autogroup_enabled",
        "net.core.rmem_max",
        "net.core.wmem_max",
        "net.ipv4.tcp_rmem",
        "net.ipv4.tcp_wmem",
        "net.ipv4.tcp_fin_timeout",
        "net.ipv4.tcp_tw_reuse",
        "net.ipv4.ip_forward",
        "net.ipv4.tcp_keepalive_time",
        "net.ipv4.tcp_keepalive_intvl",
        "net.ipv4.tcp_keepalive_probes",
        "vm.swappiness",
        "vm.overcommit_memory",
        "fs.file-max",
    ]
    res: Dict[str, str] = {}
    has_sysctl = shutil.which("sysctl") is not None
    for k in sysctl_keys:
        val = ""
        if has_sysctl:
            val = _run_cmd(["sysctl", "-n", k])
        if not val:
            # Fallback direct proc read: /proc/sys/net/ipv4/tcp_rmem
            proc_path = "/proc/sys/" + k.replace(".", "/")
            val = _read_file(proc_path)
            if val:
                val = " ".join(val.split())
        if val:
            yaml_k = k.replace(".", "_")
            res[yaml_k] = val
    return res


def collect_cpu_power_isolation() -> Dict[str, str]:
    """3. CPU ISOLATION, POWER (GOVERNOR/C-STATES) & BOOT PARAMS"""
    res: Dict[str, str] = {}
    cmdline = _read_file("/proc/cmdline")
    if cmdline:
        m_iso = re.search(r"(?:^|\s)isolcpus=(\S+)", cmdline)
        if m_iso:
            res["isolcpus"] = m_iso.group(1)
        m_nohz = re.search(r"(?:^|\s)nohz_full=(\S+)", cmdline)
        if m_nohz:
            res["nohz_full"] = m_nohz.group(1)

    gov = _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov:
        res["cpufreq_governor"] = gov

    cstates_dir = "/sys/devices/system/cpu/cpu0/cpuidle"
    if os.path.isdir(cstates_dir):
        disabled_count = 0
        try:
            for sdir in glob.glob(os.path.join(cstates_dir, "state*")):
                dis_val = _read_file(os.path.join(sdir, "disable"))
                if dis_val == "1":
                    disabled_count += 1
            res["disabled_cstates_cpu0"] = str(disabled_count)
        except Exception:
            pass
    return res


def collect_irq_affinity() -> Dict[str, str]:
    """4. IRQ AFFINITY & IRQBALANCE STATE"""
    res: Dict[str, str] = {}
    irqbal = _run_cmd(["systemctl", "is-enabled", "irqbalance"])
    if irqbal and irqbal != "not-found":
        res["irqbalance_status"] = irqbal

    affinity = _read_file("/proc/irq/default_smp_affinity")
    if affinity:
        res["default_smp_affinity"] = affinity
    return res


def collect_nic_ethtool() -> Dict[str, Any]:
    """5. NIC & ETHTOOL (DRIVER, FIRMWARE, RINGS, COALESCING, OFFLOADS)"""
    res: Dict[str, Any] = {}
    if not shutil.which("ethtool"):
        return res

    # Select primary physical interface
    intf = ""
    net_dir = "/sys/class/net"
    if os.path.isdir(net_dir):
        try:
            for name in sorted(os.listdir(net_dir)):
                if not re.match(r"^(lo|docker|veth|br|vlan|bond)", name):
                    intf = name
                    break
        except Exception:
            pass

    if not intf:
        return res

    res["sample_physical_interface"] = intf

    driver_info = _run_cmd(["ethtool", "-i", intf])
    if driver_info:
        for line in driver_info.splitlines():
            line_l = line.lower()
            if line_l.startswith("driver:"):
                res["driver"] = line.split(":", 1)[1].strip()
            elif line_l.startswith("version:"):
                res["driver_version"] = line.split(":", 1)[1].strip()
            elif line_l.startswith("firmware-version:"):
                res["firmware_version"] = line.split(":", 1)[1].strip()

    ring_info = _run_cmd(["ethtool", "-g", intf])
    if ring_info:
        # Match under "Current hardware settings:"
        in_curr = False
        for line in ring_info.splitlines():
            if "Current hardware settings:" in line:
                in_curr = True
                continue
            if in_curr:
                line_s = line.strip()
                if line_s.startswith("RX:"):
                    parts = line_s.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        res["ring_rx"] = parts[1]
                elif line_s.startswith("TX:"):
                    parts = line_s.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        res["ring_tx"] = parts[1]

    coal_info = _run_cmd(["ethtool", "-c", intf])
    if coal_info:
        for line in coal_info.splitlines():
            if "rx-usecs:" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    res["coalesce_rx_usecs"] = parts[1]
            elif "tx-usecs:" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    res["coalesce_tx_usecs"] = parts[1]

    offloads_raw = _run_cmd(["ethtool", "-k", intf])
    if offloads_raw:
        for line in offloads_raw.splitlines():
            if "[fixed]" in line:
                continue
            if re.search(r"(checksumming|segmentation|large-receive-offload):", line):
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    clean_k = parts[0].strip().replace("-", "_")
                    clean_v = parts[1].strip()
                    res[clean_k] = clean_v

    return res


def collect_onload_solarflare() -> Dict[str, str]:
    """6. ONLOAD / ACCELERATION STACK & ENV PROFILES"""
    res: Dict[str, str] = {}
    if shutil.which("onload"):
        ver = _run_cmd(["onload", "--version"])
        if ver:
            res["installed"] = "YES"
            res["version"] = ver.splitlines()[0].strip()
            if os.path.isfile("/etc/onload.cfg"):
                res["config_present"] = "YES"
    return res


def collect_hugepages_tuned() -> Dict[str, str]:
    """7. HUGEPAGES & SYSTEM TUNED PROFILE"""
    res: Dict[str, str] = {}
    for size in ("2M", "1G"):
        hp_path = f"/sys/kernel/mm/hugepages/hugepages-{size}/nr_hugepages"
        nr = _read_file(hp_path)
        if nr:
            res[f"hugepages_{size}_nr"] = nr

    thp_en = _read_file("/sys/kernel/mm/transparent_hugepage/enabled")
    if thp_en:
        m = re.search(r"\[([^\]]+)\]", thp_en)
        res["thp_enabled"] = m.group(1) if m else thp_en

    thp_def = _read_file("/sys/kernel/mm/transparent_hugepage/defrag")
    if thp_def:
        m = re.search(r"\[([^\]]+)\]", thp_def)
        res["thp_defrag"] = m.group(1) if m else thp_def

    if shutil.which("tuned-adm"):
        prof = _run_cmd(["tuned-adm", "active"])
        if prof and "None" not in prof:
            res["tuned_active_profile"] = prof.split()[-1]

    return res


def collect_time_sync() -> Dict[str, str]:
    """8. NTP / PTP TIME SYNC STATE"""
    res: Dict[str, str] = {}
    if shutil.which("chronyc"):
        track = _run_cmd(["chronyc", "tracking"])
        for line in track.splitlines():
            if "Leap status" in line:
                res["chrony_sync_status"] = line.split(":", 1)[1].strip()
                break
    elif shutil.which("ntpq"):
        peers = _run_cmd(["ntpq", "-p"])
        for line in peers.splitlines():
            if line.startswith("*"):
                res["ntp_active_peer"] = line.split()[0].lstrip("*")
                break

    ptp_svc = _run_cmd(["systemctl", "is-active", "ptp4l"])
    if ptp_svc and ptp_svc != "unknown":
        res["ptp4l_status"] = ptp_svc
    return res


def collect_core_services() -> Dict[str, str]:
    """9a. CRITICAL SERVICES"""
    res: Dict[str, str] = {}
    services = ["irqbalance", "chronyd", "haproxy", "keepalived", "ptp4l"]
    for svc in services:
        st = _run_cmd(["systemctl", "is-enabled", svc])
        if st and st != "not-found":
            res[svc] = st
    return res


def collect_config_checksums() -> Dict[str, str]:
    """9b. CONFIG CHECKSUMS"""
    res: Dict[str, str] = {}
    config_files = [
        "/etc/chrony.conf",
        "/etc/ptp4l.conf",
        "/etc/haproxy/haproxy.cfg",
        "/etc/keepalived/keepalived.conf",
        "/etc/onload.cfg",
        "/etc/sysctl.conf",
    ]
    for cfg in config_files:
        if os.path.isfile(cfg):
            yaml_k = os.path.basename(cfg).replace(".", "_") + "_hash"
            h = _file_md5(cfg)
            if h:
                res[yaml_k] = h
    return res


def collect_file_modification_checks() -> Dict[str, Any]:
    """10. FILE MODIFICATION & INTEGRITY CHECKS"""
    res: Dict[str, Any] = {}

    # Check 1: Binary drift via package manager checksums
    if shutil.which("rpm"):
        rpm_out = _run_cmd(["rpm", "-Va"], timeout=5.0)
        mods = []
        for line in rpm_out.splitlines():
            if re.match(r"^..5", line):
                parts = line.split()
                if parts:
                    mods.append(parts[-1])
        if mods:
            res["modified_package_files"] = mods[:20]
    elif shutil.which("dpkg"):
        dpkg_out = _run_cmd(["dpkg", "-V"], timeout=5.0)
        mods = []
        for line in dpkg_out.splitlines():
            if re.match(r"^..5", line):
                parts = line.split()
                if parts:
                    mods.append(parts[-1])
        if mods:
            res["modified_package_files"] = mods[:20]

    # Check 2: Recently modified files in config trees (last 30 days, maxdepth 3)
    search_dirs = ["/etc", "/usr/local/bin", "/usr/local/etc"]
    cutoff = time.time() - (30 * 86400)
    recent: List[str] = []
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for root, dirs, files in os.walk(d):
                depth = len(os.path.relpath(root, d).split(os.sep))
                if depth > 3:
                    dirs.clear()
                    continue
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        if st.st_mtime >= cutoff:
                            recent.append(fp)
                            if len(recent) >= 15:
                                break
                    except Exception:
                        pass
                if len(recent) >= 15:
                    break
        except Exception:
            pass

    if recent:
        res["recently_modified_config_trees"] = recent
    return res


def collect_network_snapshot(output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Run all 10 collectors and return a clean, unified settings dictionary.
    Optionally saves config-snapshot.yaml and config-snapshot.json to output_dir.
    """
    snapshot: Dict[str, Any] = {
        "metadata": collect_os_metadata(),
        "sysctl_kernel": collect_sysctl_params(),
        "cpu_isolation_power": collect_cpu_power_isolation(),
        "irq_affinity": collect_irq_affinity(),
        "nic_ethtool": collect_nic_ethtool(),
        "onload_solarflare": collect_onload_solarflare(),
        "hugepages_tuned": collect_hugepages_tuned(),
        "time_synchronization": collect_time_sync(),
        "core_services": collect_core_services(),
        "config_checksums": collect_config_checksums(),
        "file_modification_checks": collect_file_modification_checks(),
    }

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        # 1. Save JSON representation
        json_path = out_p / "config-snapshot.json"
        tmp_json = str(json_path) + ".tmp"
        with open(tmp_json, "w", encoding="utf-8") as jf:
            json.dump(snapshot, jf, indent=2, sort_keys=True)
        os.replace(tmp_json, str(json_path))

        # 2. Save YAML representation (backward-compatible)
        yaml_lines = ["---"]
        for section, content in snapshot.items():
            if not content:
                continue
            yaml_lines.append(f"{section}:")
            if isinstance(content, dict):
                for k, v in sorted(content.items()):
                    if isinstance(v, list):
                        yaml_lines.append(f"  {k}:")
                        for item in v:
                            yaml_lines.append(f'    - "{item}"')
                    elif isinstance(v, dict):
                        yaml_lines.append(f"  {k}:")
                        for sub_k, sub_v in sorted(v.items()):
                            yaml_lines.append(f'    {sub_k}: "{sub_v}"')
                    else:
                        yaml_lines.append(f'  {k}: "{v}"')
            yaml_lines.append("")

        yaml_path = out_p / "config-snapshot.yaml"
        tmp_yaml = str(yaml_path) + ".tmp"
        with open(tmp_yaml, "w", encoding="utf-8") as yf:
            yf.write("\n".join(yaml_lines) + "\n")
        os.replace(tmp_yaml, str(yaml_path))

    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Server Configuration & Network Settings Collector"
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="Output",
        help="Directory to write config-snapshot.yaml and config-snapshot.json (default: Output)",
    )
    args = parser.parse_args()

    out_dir = os.path.abspath(args.output_dir)
    snapshot = collect_network_snapshot(out_dir)
    yaml_path = os.path.join(out_dir, "config-snapshot.yaml")
    json_path = os.path.join(out_dir, "config-snapshot.json")
    print(f"[OK] Snapshot created: {yaml_path}")
    print(f"[OK] JSON snapshot created: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
