"""Fail-closed split-tunnel transaction planner tests."""
import unittest

from services.routing_inspector import RoutingSnapshot
from services.split_tunnel_planner import build_split_tunnel_plan


def snapshot():
    return RoutingSnapshot(
        connected=True,
        tunnel_interface="tun0",
        vpn_tables=("880",),
        ipv4_routes=({"dst": "default", "dev": "tun0", "table": 880},),
        ipv6_routes=({"dst": "::/0", "dev": "tun0", "table": 880},),
        rules=({"priority": 0, "table": "local"}, {"priority": 32766, "table": "main"}),
        warnings=(),
    )


class SplitTunnelPlannerTests(unittest.TestCase):
    def test_fails_closed_without_script_and_dns_policy(self):
        plan = build_split_tunnel_plan(
            snapshot(),
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="AUTO",
        )
        self.assertFalse(plan.ready)
        self.assertIsNone(plan.nft_batch)
        self.assertTrue(any("SCRIPT" in reason for reason in plan.reasons))
        self.assertTrue(any("DNS" in reason for reason in plan.reasons))

    def test_builds_transaction_only_when_all_safety_gates_pass(self):
        plan = build_split_tunnel_plan(
            snapshot(),
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT",
            dns_policy_ready=True,
            nft_table_absent=True,
        )
        self.assertTrue(plan.ready)
        self.assertIn("type route hook output priority mangle", plan.nft_batch)
        self.assertIn("socket cgroupv2 level 5 app-adguard-vpn.slice", plan.nft_batch)
        self.assertEqual(plan.route_table, 880)
        self.assertIn("lookup 880", " ".join(plan.ip_rule_add))
        self.assertIn("del", plan.ip_rule_delete)

    def test_requires_both_ip_families(self):
        base = snapshot()
        incomplete = RoutingSnapshot(
            connected=base.connected,
            tunnel_interface=base.tunnel_interface,
            vpn_tables=base.vpn_tables,
            ipv4_routes=base.ipv4_routes,
            ipv6_routes=(),
            rules=base.rules,
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            incomplete,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT",
            dns_policy_ready=True,
            nft_table_absent=True,
        )
        self.assertFalse(plan.ready)
        self.assertTrue(any("IPv6" in reason for reason in plan.reasons))

    def test_reuses_existing_owned_rule_for_shared_apps(self):
        base = snapshot()
        active = RoutingSnapshot(
            connected=base.connected,
            tunnel_interface=base.tunnel_interface,
            vpn_tables=base.vpn_tables,
            ipv4_routes=base.ipv4_routes,
            ipv6_routes=base.ipv6_routes,
            rules=base.rules + (
                {"priority": 1061, "fwmark": "0xad61", "table": 880},
            ),
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            active,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT", dns_policy_ready=True, nft_table_absent=True,
        )
        self.assertTrue(plan.ready)
        self.assertEqual(plan.rule_priority, 1061)

    def test_refuses_foreign_rule_using_same_mark(self):
        base = snapshot()
        conflict = RoutingSnapshot(
            connected=base.connected, tunnel_interface=base.tunnel_interface,
            vpn_tables=base.vpn_tables, ipv4_routes=base.ipv4_routes,
            ipv6_routes=base.ipv6_routes,
            rules=base.rules + ({"priority": 1061, "fwmark": "0xad61", "table": 881},),
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            conflict,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT", dns_policy_ready=True, nft_table_absent=True,
        )
        self.assertFalse(plan.ready)


    def test_requires_both_families_in_the_same_selected_vpn_table(self):
        base = snapshot()
        split_tables = RoutingSnapshot(
            connected=base.connected,
            tunnel_interface=base.tunnel_interface,
            vpn_tables=base.vpn_tables,
            ipv4_routes=base.ipv4_routes,
            ipv6_routes=({"dst": "::/0", "dev": "tun0", "table": 881},),
            rules=base.rules,
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            split_tables,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT",
            dns_policy_ready=True,
            nft_table_absent=True,
        )
        self.assertFalse(plan.ready)
        self.assertIsNone(plan.nft_batch)
        self.assertTrue(any("IPv6" in reason and "880" in reason for reason in plan.reasons))

    def test_rejects_route_through_tunnel_when_route_table_is_missing(self):
        base = snapshot()
        missing_table = RoutingSnapshot(
            connected=base.connected,
            tunnel_interface=base.tunnel_interface,
            vpn_tables=base.vpn_tables,
            ipv4_routes=({"dst": "default", "dev": "tun0"},),
            ipv6_routes=base.ipv6_routes,
            rules=base.rules,
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            missing_table,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT",
            dns_policy_ready=True,
            nft_table_absent=True,
        )
        self.assertFalse(plan.ready)
        self.assertTrue(any("IPv4" in reason for reason in plan.reasons))

    def test_rejects_multiple_vpn_tables(self):
        base = snapshot()
        ambiguous = RoutingSnapshot(
            connected=True,
            tunnel_interface="tun0",
            vpn_tables=("880", "881"),
            ipv4_routes=base.ipv4_routes,
            ipv6_routes=base.ipv6_routes,
            rules=base.rules,
            warnings=(),
        )
        plan = build_split_tunnel_plan(
            ambiguous,
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-adguard-vpn.slice",
            routing_mode="SCRIPT",
            dns_policy_ready=True,
        )
        self.assertFalse(plan.ready)
        self.assertIsNone(plan.route_table)


if __name__ == "__main__":
    unittest.main()
