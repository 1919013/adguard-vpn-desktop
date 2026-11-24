# ADGuard VPN Desktop

Open-source GTK desktop interface for **AdGuard VPN CLI** on Linux. This project is a community GUI wrapper; it is not the official AdGuard desktop application and is not affiliated with AdGuard.

## Current implementation status

- AdGuard VPN CLI connection, disconnection, status and location selection.
- Read-only discovery of network interfaces, IP addresses and NetworkManager device state.
- A status line reports the tunnel interface named by AdGuard VPN CLI (for example, `tun0`).
- An experimental DNS tab with backup validation and guarded operations limited to explicitly allowlisted test profiles.

## Not yet implemented or verified

- The Applications tab discovers Debian and Flatpak `.desktop` entries, supports case-insensitive prefix search and custom executable paths, and persists selected entries in `~/.config/adguard-vpn-desktop/applications.json` with mode `0600`. This is still only a saved selection: it does not change routing.
- The split-tunnel backend includes scoped native/Flatpak launch primitives, route inspection, a fail-closed planner and a separate privileged helper with preflight checks and rollback. The helper is not yet connected to the GUI/polkit; DNS policy is not ready, no rules are applied, and no application traffic is routed.
- Applying selected network interfaces to routing. The Interfaces tab currently discovers and displays devices; its checkboxes are temporary selections only.
- General-purpose DNS management for arbitrary user NetworkManager profiles.
- AdGuard product management, desktop-wrapper updates, full settings and browser-based help.
- End-to-end verification of routing, DNS leaks and IPv6 on supported Debian systems.

## Split-tunneling design constraint

The documented AdGuard VPN CLI Linux interface provides TUN/SOCKS modes, tunnel routing modes (`AUTO`, `SCRIPT`, `NONE`) and **domain** exclusions through `site-exclusions`. Its documented exclusions are not a per-process application selector. The custom routing script is a supported extension point for route-level policies, but it does not by itself provide an application picker.

Therefore, this project must not present an application checkbox as working split tunneling until a separate Linux process-aware routing mechanism is implemented and verified. See the [AdGuard VPN for Linux settings documentation](https://adguard-vpn.com/kb/adguard-vpn-for-linux/settings/) and [exclusions documentation](https://adguard-vpn.com/kb/adguard-vpn-for-linux/exclusions/).

## Architecture

- `core/`: CLI integration and application logic.
- `modules/`: user-facing features.
- `services/`: operating-system integration.
- `ui/`: GTK interface.
- `i18n/`: translations.
- `docs/`: documentation.
- `tests/`: automated tests.

The UI must not execute operating-system commands directly. System operations are isolated behind core/service interfaces.

## Safety

- Interface discovery is read-only.
- DNS changes are restricted to named test profiles; production profiles are not modified.
- DNS changes require a validated backup and verified rollback.
- Do not claim split tunneling is ready until routing, DNS and IPv6 are verified.
- Never commit credentials, private keys or local DNS snapshots.

## License

The project is intended to use **GPL-3.0-or-later**, as agreed for this project. The canonical license text still needs to be added to the repository before release.

See [README.ru.md](README.ru.md) for Russian.
