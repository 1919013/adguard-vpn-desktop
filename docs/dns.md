# DNS and protection

The current DNS tab provides a provider selector for development and testing. It lists AdGuard DNS filtering, unfiltered and family variants; Cloudflare; Google Public DNS; OpenDNS; Quad9; Mullvad DNS; system settings; and custom IP addresses.

**Important safety boundary:** writes are restricted to two explicitly allowlisted, dedicated test NetworkManager profiles. Active profiles are rejected. Ordinary user connections are not modified. A backup must be created and validated before applying changes; restore validates the snapshot and verifies the result.

The system-DNS choice restores the saved test-profile settings. It does not mean that the application has installed a general DNS provider for every active network connection.

This is not yet general-purpose DNS management and is not a DNS leak test. Do not assume that selecting a provider changes DNS for the currently active Wi-Fi or Ethernet connection.
