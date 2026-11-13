"""Tests for native AdGuard VPN website exclusion helpers."""
import unittest
from modules.site_exclusions import (
    command, validate_domains, set_mode, add_exclusions,
)


class SiteExclusionTests(unittest.TestCase):
    def test_domain_validation_and_wildcards(self):
        self.assertEqual(validate_domains("example.org *.example.net"), ["example.org", "*.example.net"])

    def test_duplicate_domains_are_removed_case_insensitively(self):
        self.assertEqual(validate_domains(["Example.org", "example.org"]), ["Example.org"])

    def test_invalid_domains_are_rejected(self):
        for value in ("https://example.org", "localhost", "-bad.example", "bad domain"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_domains(value)

    def test_cli_command_is_native_site_exclusions(self):
        self.assertEqual(command("mode", "selective"), [
            "adguardvpn-cli", "site-exclusions", "mode", "selective"
        ])

    def test_mode_validation_prevents_arbitrary_cli_arguments(self):
        with self.assertRaises(ValueError):
            set_mode("all")
        with self.assertRaises(ValueError):
            add_exclusions("example.org", "all")


if __name__ == "__main__":
    unittest.main()
