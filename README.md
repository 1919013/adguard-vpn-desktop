# ADGuard VPN Desktop

Open-source GTK desktop interface for **AdGuard VPN CLI** on Linux. This is a community GUI wrapper, not the official AdGuard desktop application, and is not affiliated with AdGuard.

## Current implementation

- AdGuard VPN CLI connection, disconnection, status and location selection.
- Read-only discovery of network interfaces, IP addresses and NetworkManager device state.
- Applications catalog for Debian and Flatpak desktop entries, case-insensitive prefix search, custom executable paths and persistent selection.
- Per-application **Launch through VPN** action using a gated systemd user scope: the target process is held until routing rules are installed and independently verified.
- Narrow root helper invoked through pkexec and a dedicated polkit action.
- VPN status watcher. If the CLI disconnects or changes TUN interface, the application scope is stopped.
- DNS preflight: the active /etc/resolv.conf must exactly match the AdGuard VPN CLI resolver file, and each resolver address must route through the active TUN.
- nftables guards mark the selected app's sockets and DNS packets to the verified CLI resolver addresses. Marked app traffic and those DNS requests are dropped if their output interface is not the active TUN.
- Debian package metadata and CI package-build workflow.

## Important limitations

- Protected applications now join one shared `app-adguard-vpn.slice`, each in a separate systemd scope. A single nftables/ip-rule policy marks sockets at the parent cgroup; later launches verify and reuse that policy. Cleanup is deferred while any protected process remains in the shared cgroup. Concurrent Chrome + Telegram is now implemented in the launch architecture but still requires CI and live Debian 13 validation.
- D-Bus-activatable applications and already-running instances are refused to avoid forwarding requests to processes outside the protected cgroup.
- Local DNS stub resolvers such as systemd-resolved/dnsmasq are refused until their upstream servers can be verified safely.
- The VPN watcher polls CLI status. If the GUI supervisor remains alive, it terminates the app on disconnect; kernel egress guards remain as the fail-closed backstop if the TUN route disappears.
- The DNS preflight is deliberately strict. If system DNS is not set to the AdGuard VPN CLI resolver addresses and routed through TUN, the app is not launched.
- The package build is exercised in GitHub Actions, but installation and real traffic tests have not yet been performed on Debian 13. Do not treat split tunneling as production-ready until those tests pass.
- The DNS tab still has limited operations restricted to explicitly allowlisted test profiles; it is not general-purpose NetworkManager DNS management.
- Applying selected network interfaces, full AdGuard product management and browser-based help remain unfinished.

## Split-tunneling design constraint

AdGuard VPN CLI provides TUN/SOCKS modes, tunnel routing modes (AUTO, SCRIPT, NONE) and domain exclusions through site-exclusions. Domain exclusions are not a per-process application selector. The process-aware routing in this project is a separate Linux mechanism layered on top of the CLI.

See the [AdGuard VPN for Linux settings documentation](https://adguard-vpn.com/kb/adguard-vpn-for-linux/settings/) and [exclusions documentation](https://adguard-vpn.com/kb/adguard-vpn-for-linux/exclusions/).

## Architecture

- core/: CLI integration and application logic.
- modules/: user-facing features.
- services/: operating-system integration.
- ui/: GTK interface.
- i18n/: translations.
- docs/: documentation.
- tests/: automated tests.

The UI must not execute privileged operating-system commands directly. Privileged operations are restricted to the fixed helper and validated arguments.

## Safety

- Network interface discovery and DNS preflight are read-only.
- DNS firewall guards apply only to the active protected-app session and the resolver addresses verified before launch.
- Existing nftables tables are never adopted or overwritten.
- Helper-owned routing state is stored with restrictive permissions and removed after the protected application exits.
- Never commit credentials, private keys or local DNS snapshots.

## License

The project is intended to use **GPL-3.0-or-later**. See Debian copyright metadata; the canonical full license text should be included before release.

See [README.ru.md](README.ru.md) for Russian.
