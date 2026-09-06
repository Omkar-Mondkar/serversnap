#!/usr/bin/env python3
"""
test_network_drift.py
=====================

Unit and integration tests for Network Tab UI & Drift Detection:
1. parse_network_settings includes all 10 YAML sections.
2. BaselineManager detects network drift in nested sections.
3. BaselineManager returns no changes when network data is unchanged.
4. build_dashboard_html embeds network_diff into threshold data and renders elements.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Add bin to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from baseline_manager import BaselineManager
from visualize_report import parse_network_settings, build_dashboard_html


class TestNetworkDrift(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="serversnap_net_test_")
        self.baselines_dir = os.path.join(self.test_dir, "baselines")
        os.makedirs(self.baselines_dir, exist_ok=True)
        self.server_id = "test-net-srv"
        self.bm = BaselineManager(self.server_id, self.baselines_dir)

        # Sample raw YAML dictionary with all 10 sections
        self.sample_yaml = {
            "metadata": {
                "os_version": "Ubuntu 22.04.4 LTS",
                "kernel_release": "5.15.0-105-generic",
            },
            "sysctl_kernel": {
                "net_ipv4_tcp_fin_timeout": 60,
                "net_ipv4_tcp_keepalive_time": 7200,
                "vm_swappiness": 10,
            },
            "cpu_isolation_power": {
                "cpufreq_governor": "performance",
                "isolcpus": "none",
            },
            "irq_affinity": {
                "irqbalance_status": "active",
                "default_smp_affinity": "ff",
            },
            "nic_ethtool": {
                "driver": "mlx5_core",
                "ring_rx": 4096,
                "ring_tx": 4096,
            },
            "onload_solarflare": {
                "installed": "no",
                "version": "none",
            },
            "hugepages_tuned": {
                "hugepages_2M_nr": 1024,
                "tuned_active_profile": "throughput-performance",
            },
            "time_synchronization": {
                "chrony_sync_status": "synchronized",
                "ntp_active_peer": "10.0.0.1",
            },
            "core_services": {
                "chronyd": "enabled",
                "haproxy": "disabled",
            },
            "config_checksums": {
                "sysctl_conf_sha256": "abc123def456",
            },
            "file_modification_checks": {
                "modified_files_24h": ["/etc/sysctl.conf"],
            },
        }

    def test_parse_network_settings_all_sections(self):
        """Verify parse_network_settings includes all 10 sections."""
        parsed = parse_network_settings(self.sample_yaml)
        expected_sections = [
            "metadata",
            "sysctl_kernel",
            "cpu_isolation_power",
            "irq_affinity",
            "nic_ethtool",
            "onload_solarflare",
            "hugepages_tuned",
            "time_synchronization",
            "core_services",
            "config_checksums",
            "file_modification_checks",
        ]
        for sec in expected_sections:
            self.assertIn(sec, parsed, f"Missing section: {sec}")
            self.assertEqual(parsed[sec], self.sample_yaml[sec])

    def test_network_baseline_and_drift_detection(self):
        """Verify baseline saving and subsequent drift detection."""
        parsed_baseline = parse_network_settings(self.sample_yaml)
        self.bm.save_baseline("network", parsed_baseline, reason="initial_network_baseline")

        # 1. Compare identical data -> no changes
        has_changes, diff = self.bm.compare_with_baseline("network", parsed_baseline)
        self.assertFalse(has_changes)
        self.assertEqual(diff.get("status"), "no_changes")

        # 2. Modify one sysctl value and one service value
        modified_yaml = dict(self.sample_yaml)
        modified_yaml["sysctl_kernel"] = dict(self.sample_yaml["sysctl_kernel"])
        modified_yaml["sysctl_kernel"]["net_ipv4_tcp_fin_timeout"] = 30  # changed 60 -> 30

        modified_yaml["core_services"] = dict(self.sample_yaml["core_services"])
        modified_yaml["core_services"]["haproxy"] = "enabled"  # changed disabled -> enabled

        parsed_new = parse_network_settings(modified_yaml)
        has_changes, diff = self.bm.compare_with_baseline("network", parsed_new)
        self.assertTrue(has_changes)
        self.assertIn("modified_settings", diff)
        
        mod = diff["modified_settings"]
        self.assertIn("net_ipv4_tcp_fin_timeout", mod)
        self.assertEqual(mod["net_ipv4_tcp_fin_timeout"]["old"], 60)
        self.assertEqual(mod["net_ipv4_tcp_fin_timeout"]["new"], 30)
        self.assertEqual(mod["net_ipv4_tcp_fin_timeout"]["section"], "sysctl_kernel")

        self.assertIn("haproxy", mod)
        self.assertEqual(mod["haproxy"]["old"], "disabled")
        self.assertEqual(mod["haproxy"]["new"], "enabled")
        self.assertEqual(mod["haproxy"]["section"], "core_services")

    def test_build_dashboard_html_network_drift_embedding(self):
        """Verify build_dashboard_html embeds network_diff into threshold data."""
        network_diff = {
            "status": "changes_detected",
            "modified_settings": {
                "net_ipv4_tcp_fin_timeout": {
                    "old": 60,
                    "new": 30,
                    "section": "sysctl_kernel",
                }
            }
        }
        parsed = parse_network_settings(self.sample_yaml)
        entries = [{"data": {"server_id": self.server_id}}]
        html = build_dashboard_html(
            entries=entries,
            title="Test Dashboard",
            network_data=parsed,
            network_diff=network_diff,
        )

        # Confirm new elements exist in HTML
        self.assertIn('id="netDriftBanner"', html)
        self.assertIn('id="netSectionsContainer"', html)
        self.assertIn('id="netExpandAllBtn"', html)
        self.assertIn('id="netCollapseAllBtn"', html)
        self.assertIn("net-sections-grid", html)
        self.assertIn("net-section-body", html)
        self.assertIn("net-sec-chevron", html)

        # Confirm threshold data contains network_diff
        self.assertIn('"network_diff":', html)
        self.assertIn('"net_ipv4_tcp_fin_timeout":', html)


if __name__ == "__main__":
    unittest.main()
