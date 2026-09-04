#!/bin/bash
# ============================================================================
# Server Configuration Snapshot Collector (Golden Baseline / Diff-Friendly)
# Captures configuration state across 10 key categories for drift detection.
# Includes system binary verification and recent file modification detection.
# ============================================================================


set -euo pipefail


# Accept output directory as optional parameter (default: ./Output)
OUTPUT_DIR="${1:-Output}"
SNAPSHOT_FILE="${OUTPUT_DIR}/config-snapshot.yaml"


mkdir -p "$OUTPUT_DIR"


# Initialize YAML structure
cat > "$SNAPSHOT_FILE" <<'EOF'
---
metadata:
EOF


# ============================================================================
# 1. OS & KERNEL METADATA
# ============================================================================
OS_VER=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2 || true)
KERNEL_VER=$(uname -r 2>/dev/null || true)


[[ -n "$OS_VER" ]]     && echo "  os_version: \"$OS_VER\"" >> "$SNAPSHOT_FILE"
[[ -n "$KERNEL_VER" ]] && echo "  kernel_release: \"$KERNEL_VER\"" >> "$SNAPSHOT_FILE"


# ============================================================================
# 2. SYSCTL & TCP KEEPALIVE PARAMS
# ============================================================================
SYSCTL_KEYS=(
    "kernel.sched_migration_cost_ns"
    "kernel.sched_latency_ns"
    "kernel.sched_min_granularity_ns"
    "kernel.sched_autogroup_enabled"
    "net.core.rmem_max"
    "net.core.wmem_max"
    "net.ipv4.tcp_rmem"
    "net.ipv4.tcp_wmem"
    "net.ipv4.tcp_fin_timeout"
    "net.ipv4.tcp_tw_reuse"
    "net.ipv4.ip_forward"
    "net.ipv4.tcp_keepalive_time"
    "net.ipv4.tcp_keepalive_intvl"
    "net.ipv4.tcp_keepalive_probes"
    "vm.swappiness"
    "vm.overcommit_memory"
    "fs.file-max"
)


SYSCTL_BUF=""
for key in "${SYSCTL_KEYS[@]}"; do
    val=$(sysctl -n "$key" 2>/dev/null || true)
    if [[ -n "$val" ]]; then
        yaml_key="${key//./_}"
        SYSCTL_BUF+="  ${yaml_key}: \"${val}\"\n"
    fi
done


if [[ -n "$SYSCTL_BUF" ]]; then
    echo -e "\nsysctl_kernel:" >> "$SNAPSHOT_FILE"
    echo -e -n "$SYSCTL_BUF" >> "$SNAPSHOT_FILE"
fi


# ============================================================================
# 3. CPU ISOLATION, POWER (GOVERNOR/C-STATES) & BOOT PARAMS
# ============================================================================
CPU_BUF=""
ISOLCPUS=$(grep -oP '(?<=isolcpus=)\S+' /proc/cmdline 2>/dev/null || true)
NOHZ=$(grep -oP '(?<=nohz_full=)\S+' /proc/cmdline 2>/dev/null || true)


[[ -n "$ISOLCPUS" ]] && CPU_BUF+="  isolcpus: \"$ISOLCPUS\"\n"
[[ -n "$NOHZ" ]]     && CPU_BUF+="  nohz_full: \"$NOHZ\"\n"


# CPU Scaling Governor
if [[ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]]; then
    GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)
    [[ -n "$GOV" ]] && CPU_BUF+="  cpufreq_governor: \"$GOV\"\n"
fi


# Disabled C-States summary
if [[ -d /sys/devices/system/cpu/cpu0/cpuidle ]]; then
    DISABLED_CSTATES=0
    for state_dir in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
        if [[ -f "${state_dir}/disable" ]]; then
            dis=$(cat "${state_dir}/disable" 2>/dev/null || echo "0")
            if [[ "$dis" == "1" ]]; then
                ((DISABLED_CSTATES++)) || true
            fi
        fi
    done
    CPU_BUF+="  disabled_cstates_cpu0: \"${DISABLED_CSTATES}\"\n"
fi


if [[ -n "$CPU_BUF" ]]; then
    echo -e "\ncpu_isolation_power:" >> "$SNAPSHOT_FILE"
    echo -e -n "$CPU_BUF" >> "$SNAPSHOT_FILE"
fi


# ============================================================================
# 4. IRQ AFFINITY & IRQBALANCE STATE
# ============================================================================
IRQ_BUF=""
IRQBAL_STATE=$(systemctl is-enabled irqbalance 2>/dev/null || true)
[[ -n "$IRQBAL_STATE" && "$IRQBAL_STATE" != "not-found" ]] && IRQ_BUF+="  irqbalance_status: \"${IRQBAL_STATE}\"\n"


if [[ -f /proc/irq/default_smp_affinity ]]; then
    DEFAULT_AFFINITY=$(cat /proc/irq/default_smp_affinity 2>/dev/null || true)
    [[ -n "$DEFAULT_AFFINITY" ]] && IRQ_BUF+="  default_smp_affinity: \"${DEFAULT_AFFINITY}\"\n"
fi


if [[ -n "$IRQ_BUF" ]]; then
    echo -e "\nirq_affinity:" >> "$SNAPSHOT_FILE"
    echo -e -n "$IRQ_BUF" >> "$SNAPSHOT_FILE"
fi




# ============================================================================
# 5. NIC & ETHTOOL (DRIVER, FIRMWARE, RINGS, COALESCING, OFFLOADS)
# ============================================================================
if command -v ethtool &>/dev/null; then
    intf=$(ls /sys/class/net/ 2>/dev/null | grep -Ev '^(lo|docker|veth|br|vlan|bond)' | head -n 1 || true)
    if [[ -n "$intf" ]]; then
        NIC_BUF="  sample_physical_interface: \"$intf\"\n"


        # Driver & Firmware info
        DRIVER_INFO=$(ethtool -i "$intf" 2>/dev/null || true)
        if [[ -n "$DRIVER_INFO" ]]; then
            drv=$(echo "$DRIVER_INFO" | grep -i '^driver:' | awk '{print $2}' || true)
            ver=$(echo "$DRIVER_INFO" | grep -i '^version:' | awk '{print $2}' || true)
            fw=$(echo "$DRIVER_INFO" | grep -i '^firmware-version:' | awk '{print $2}' || true)
            [[ -n "$drv" ]] && NIC_BUF+="  driver: \"$drv\"\n"
            [[ -n "$ver" ]] && NIC_BUF+="  driver_version: \"$ver\"\n"
            [[ -n "$fw" ]]  && NIC_BUF+="  firmware_version: \"$fw\"\n"
        fi


        # Ring Buffers
        RINGS=$(ethtool -g "$intf" 2>/dev/null | awk '/Current hardware settings:/,/^$/' || true)
        if [[ -n "$RINGS" ]]; then
            rx_ring=$(echo "$RINGS" | grep -i '^RX:' | awk '{print $2}' | head -n 1 || true)
            tx_ring=$(echo "$RINGS" | grep -i '^TX:' | awk '{print $2}' | head -n 1 || true)
            [[ -n "$rx_ring" ]] && NIC_BUF+="  ring_rx: \"$rx_ring\"\n"
            [[ -n "$tx_ring" ]] && NIC_BUF+="  ring_tx: \"$tx_ring\"\n"
        fi


        # Coalescing Parameters
        COAL=$(ethtool -c "$intf" 2>/dev/null || true)
        if [[ -n "$COAL" ]]; then
            rx_usec=$(echo "$COAL" | grep -i 'rx-usecs:' | head -n 1 | awk '{print $2}' || true)
            tx_usec=$(echo "$COAL" | grep -i 'tx-usecs:' | head -n 1 | awk '{print $2}' || true)
            [[ -n "$rx_usec" ]] && NIC_BUF+="  coalesce_rx_usecs: \"$rx_usec\"\n"
            [[ -n "$tx_usec" ]] && NIC_BUF+="  coalesce_tx_usecs: \"$tx_usec\"\n"
        fi


        # Offloads
        OFFLOADS=$(ethtool -k "$intf" 2>/dev/null | grep -E "(checksumming|segmentation|large-receive-offload):" | grep -v '\[fixed\]' || true)
        if [[ -n "$OFFLOADS" ]]; then
            NIC_BUF+="  offloads:\n"
            while read -r key val junk; do
                clean_key=$(echo "$key" | tr -d ':' | tr '-' '_')
                NIC_BUF+="    ${clean_key}: \"${val}\"\n"
            done <<< "$OFFLOADS"
        fi


        echo -e "\nnic_ethtool:" >> "$SNAPSHOT_FILE"
        echo -e -n "$NIC_BUF" >> "$SNAPSHOT_FILE"
    fi
fi


# ============================================================================
# 6. ONLOAD / ACCELERATION STACK & ENV PROFILES
# ============================================================================
if command -v onload &>/dev/null; then
    ONLOAD_VER=$(onload --version 2>/dev/null | head -n 1 || true)
    if [[ -n "$ONLOAD_VER" ]]; then
        echo -e "\nonload_solarflare:" >> "$SNAPSHOT_FILE"
        echo "  installed: \"YES\"" >> "$SNAPSHOT_FILE"
        echo "  version: \"$ONLOAD_VER\"" >> "$SNAPSHOT_FILE"
        if [[ -f /etc/onload.cfg ]]; then
            echo "  config_present: \"YES\"" >> "$SNAPSHOT_FILE"
        fi
    fi
fi


# ============================================================================
# 7. HUGEPAGES & SYSTEM TUNED PROFILE
# ============================================================================
HP_BUF=""
for size in 2M 1G; do
    HP_PATH="/sys/kernel/mm/hugepages/hugepages-${size}"
    if [[ -d "$HP_PATH" ]]; then
        nr=$(cat "$HP_PATH/nr_hugepages" 2>/dev/null || true)
        [[ -n "$nr" ]] && HP_BUF+="  hugepages_${size}_nr: \"${nr}\"\n"
    fi
done




THP_EN=$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null | grep -oP '\[\K[^\]]+' || true)
[[ -n "$THP_EN" ]] && HP_BUF+="  thp_enabled: \"${THP_EN}\"\n"


THP_DEF=$(cat /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null | grep -oP '\[\K[^\]]+' || true)
[[ -n "$THP_DEF" ]] && HP_BUF+="  thp_defrag: \"${THP_DEF}\"\n"


if command -v tuned-adm &>/dev/null; then
    TUNED_PROF=$(tuned-adm active 2>/dev/null | awk '{print $NF}' || true)
    if [[ -n "$TUNED_PROF" && "$TUNED_PROF" != "None" ]]; then
        HP_BUF+="  tuned_active_profile: \"${TUNED_PROF}\"\n"
    fi
fi


if [[ -n "$HP_BUF" ]]; then
    echo -e "\nhugepages_tuned:" >> "$SNAPSHOT_FILE"
    echo -e -n "$HP_BUF" >> "$SNAPSHOT_FILE"
fi


# ============================================================================
# 8. NTP / PTP TIME SYNC STATE
# ============================================================================
TIME_BUF=""
if command -v chronyc &>/dev/null; then
    SYNC_STAT=$(chronyc tracking 2>/dev/null | grep -i 'Leap status' | awk -F':' '{print $2}' | xargs || true)
    [[ -n "$SYNC_STAT" ]] && TIME_BUF+="  chrony_sync_status: \"${SYNC_STAT}\"\n"
elif command -v ntpq &>/dev/null; then
    NTP_STAT=$(ntpq -p 2>/dev/null | grep -E '^\*' | awk '{print $1}' || true)
    [[ -n "$NTP_STAT" ]] && TIME_BUF+="  ntp_active_peer: \"${NTP_STAT}\"\n"
fi


PTP_SVC=$(systemctl is-active ptp4l 2>/dev/null || true)
[[ -n "$PTP_SVC" && "$PTP_SVC" != "unknown" ]] && TIME_BUF+="  ptp4l_status: \"${PTP_SVC}\"\n"


if [[ -n "$TIME_BUF" ]]; then
    echo -e "\ntime_synchronization:" >> "$SNAPSHOT_FILE"
    echo -e -n "$TIME_BUF" >> "$SNAPSHOT_FILE"
fi


# ============================================================================
# 9. HAPROXY / KEEPALIVED / CRITICAL SERVICES & CHECKSUMS
# ============================================================================
SERVICES=("irqbalance" "chronyd" "haproxy" "keepalived" "ptp4l")
SVC_BUF=""
for svc in "${SERVICES[@]}"; do
    state=$(systemctl is-enabled "$svc" 2>/dev/null || true)
    if [[ -n "$state" && "$state" != "not-found" ]]; then
        SVC_BUF+="  ${svc}: \"${state}\"\n"
    fi
done


if [[ -n "$SVC_BUF" ]]; then
    echo -e "\ncore_services:" >> "$SNAPSHOT_FILE"
    echo -e -n "$SVC_BUF" >> "$SNAPSHOT_FILE"
fi


CFG_BUF=""
CONFIG_FILES=(
    "/etc/chrony.conf"
    "/etc/ptp4l.conf"
    "/etc/haproxy/haproxy.cfg"
    "/etc/keepalived/keepalived.conf"
    "/etc/onload.cfg"
    "/etc/sysctl.conf"
)


for cfg in "${CONFIG_FILES[@]}"; do
    if [[ -f "$cfg" ]]; then
        yaml_cfg=$(basename "$cfg" | tr '.' '_')
        hash=$(md5sum "$cfg" 2>/dev/null | awk '{print $1}')
        [[ -n "$hash" ]] && CFG_BUF+="  ${yaml_cfg}_hash: \"${hash}\"\n"
    fi
done


if [[ -n "$CFG_BUF" ]]; then
    echo -e "\nconfig_checksums:" >> "$SNAPSHOT_FILE"
    echo -e -n "$CFG_BUF" >> "$SNAPSHOT_FILE"
fi




# ============================================================================
# 10. FILE MODIFICATION & INTEGRITY CHECKS
# ============================================================================
FILE_MOD_BUF=""


# Check 1: Detect binary drift via package manager verification (checksum mismatches)
if command -v rpm &>/dev/null; then
    # Verify core system binaries / config files against RPM database
    MODIFIED_RPMS=$(rpm -Va 2>/dev/null | grep -E '^..5' | awk '{print $NF}' | head -n 20 || true)
    if [[ -n "$MODIFIED_RPMS" ]]; then
        FILE_MOD_BUF+="  modified_package_files:\n"
        while read -r file; do
            FILE_MOD_BUF+="    - \"$file\"\n"
        done <<< "$MODIFIED_RPMS"
    fi
elif command -v dpkg &>/dev/null; then
    MODIFIED_DPKGS=$(dpkg -V 2>/dev/null | grep -E '^..5' | awk '{print $NF}' | head -n 20 || true)
    if [[ -n "$MODIFIED_DPKGS" ]]; then
        FILE_MOD_BUF+="  modified_package_files:\n"
        while read -r file; do
            FILE_MOD_BUF+="    - \"$file\"\n"
        done <<< "$MODIFIED_DPKGS"
    fi
fi


# Check 2: Find recently modified files in key system config directory trees (last 30 days)
SEARCH_DIRS=("/etc" "/usr/local/bin" "/usr/local/etc")
RECENT_MODS=""
for dir in "${SEARCH_DIRS[@]}"; do
    if [[ -d "$dir" ]]; then
        found=$(find "$dir" -maxdepth 3 -type f -mtime -30 2>/dev/null | head -n 10 || true)
        if [[ -n "$found" ]]; then
            RECENT_MODS+="$found"$'\n'
        fi
    fi
done


if [[ -n "$RECENT_MODS" ]]; then
    FILE_MOD_BUF+="  recently_modified_config_trees:\n"
    while read -r f; do
        if [[ -n "$f" ]]; then
            FILE_MOD_BUF+="    - \"$f\"\n"
        fi
    done <<< "$RECENT_MODS"
fi


if [[ -n "$FILE_MOD_BUF" ]]; then
    echo -e "\nfile_modification_checks:" >> "$SNAPSHOT_FILE"
    echo -e -n "$FILE_MOD_BUF" >> "$SNAPSHOT_FILE"
fi


echo "✓ Snapshot created: $SNAPSHOT_FILE"



