"""Tests for CLI configuration parsing and VPN status monitoring."""
import unittest
import threading

from services.split_tunnel_runtime import read_cli_split_tunnel_config, SplitTunnelRuntimeError
from services.vpn_status_watcher import VPNStatusWatcher


class SplitTunnelRuntimeTests(unittest.TestCase):
    def test_accepts_explicit_tun_script_and_system_dns(self):
        output = (
            "VPN mode: TUN\n"
            "VPN tunnel routing mode: SCRIPT\n"
            "Change system DNS: on\n"
        )
        result = read_cli_split_tunnel_config(lambda args, timeout=12: (0, output))
        self.assertEqual(result["routing_mode"], "SCRIPT")
        self.assertTrue(result["change_system_dns"])

    def test_refuses_auto_routing(self):
        output = (
            "VPN mode: TUN\n"
            "VPN tunnel routing mode: AUTO\n"
            "Change system DNS: on\n"
        )
        with self.assertRaises(SplitTunnelRuntimeError):
            read_cli_split_tunnel_config(lambda args, timeout=12: (0, output))

    def test_refuses_unknown_configuration_format(self):
        with self.assertRaises(SplitTunnelRuntimeError):
            read_cli_split_tunnel_config(lambda args, timeout=12: (0, "connected"))

    def test_status_parser_requires_connected_tun_interface(self):
        parser = VPNStatusWatcher._active_interface
        self.assertEqual(parser(0, "Connected to Riga running on tun0"), "tun0")
        self.assertIsNone(parser(0, "Disconnected"))
        self.assertIsNone(parser(1, "Connected to Riga running on tun0"))

    def test_stop_routing_waits_for_confirmation_without_process_action(self):
        from services.split_tunnel_runtime import SplitTunnelRuntime
        runtime = SplitTunnelRuntime.__new__(SplitTunnelRuntime)
        runtime._stop_routing_request = threading.Event()
        runtime._routing_stopped_event = threading.Event()

        def helper():
            self.assertTrue(runtime._stop_routing_request.wait(1))
            runtime._routing_stopped_event.set()

        worker = threading.Thread(target=helper)
        worker.start()
        self.assertTrue(runtime.stop_routing(timeout=1))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
