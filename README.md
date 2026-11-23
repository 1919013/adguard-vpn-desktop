# ADGuard VPN Desktop

An independent desktop GUI for **AdGuard VPN CLI** on Linux. This project is not developed, endorsed, or supported by AdGuard.

> Development status: feature branch under review. Runtime validation on target desktop systems and release packaging are still pending.

## Current feature set

- VPN CLI connection controls and server/location selection.
- AdGuard VPN CLI management: installation detection, official install/update workflow, status, connect/disconnect, cache and user-data cleanup, and separate CLI/GUI autostart controls.
- Dynamic network-interface discovery and the AdGuard VPN CLI outbound-interface override. Personal NetworkManager profile names are not hard-coded.
- A website-exclusions tab using the CLI's native General and Selective lists.
- Experimental per-application TUN split tunneling with two modes, generated application launchers, systemd user scopes, cgroup v2, nftables socket matching, and dedicated IPv4/IPv6 policy routing. Flatpak desktop entries are discovered and launched with `flatpak run` inside a scope, but actual sandbox/DBus traffic routing still requires target-system validation.
- Browser-based help with an explicit unofficial-project disclaimer.
- A DNS tab in a deliberately restricted test-only mode.

## Split tunneling

### Websites

The website-exclusions tab controls the native CLI feature:
- **General** — listed websites bypass the VPN.
- **Selective** — only listed websites use the VPN.

There is one domain list and one active mode; changing the mode changes how that same list is applied. Editing the list does not silently switch modes. The website list is independent from app selection. See the [official Linux settings documentation](https://adguard-vpn.com/kb/en/adguard-vpn-for-linux/settings/).

### Applications

Application routing uses AdGuard VPN CLI's native SCRIPT routing mode with TUN. “Only selected apps” marks sockets from apps launched through generated systemd-scope launchers. “All except selected” marks processes in the current user's systemd session for VPN and overrides the selected app scopes to use the main routing table. Marked traffic uses a dedicated route table and IPv4/IPv6 policy rules; the main routing table is not rewritten; private, link-local and multicast destinations remain on the main table for LAN access. Disconnect VPN before changing the policy, then reconnect after applying it. The disable action removes only the app's owned rules and restores the previous route script and CLI settings.

Limitations: already-running apps must be closed and relaunched through the generated launchers. Flatpak is discovered and launched in the managed scope, but sandbox/DBus traffic routing is not yet verified; Snap is not supported. DNS is not split per application: systemd-resolved requests are routed through the VPN in both modes, including for apps whose other traffic bypasses the tunnel. Other resolver implementations need separate validation. nftables socket-cgroup matching classifies socket-associated packets; raw/ICMP traffic and some sandbox scenarios need dedicated validation. Passing CI does not replace integration testing on Debian/Cinnamon. Do not enable this on a production system before that test.

## DNS

The current DNS manager is a safety test harness restricted to two explicitly allowlisted test profiles. It refuses active test profiles and refuses writes unless AdGuard VPN TUN status is confirmed. It does not modify ordinary user NetworkManager profiles. This is not production DNS management or a DNS leak test.

## Network interfaces

The interface tab discovers current non-loopback, non-tunnel devices and applies the documented `adguardvpn-cli config set-bound-if-override` setting. It does not edit NetworkManager connection profiles. The CLI setting accepts one interface; clearing the selection restores automatic interface choice.

## Development and checks

The active 0.2.0 preparation branch is `release/0.2.0`; see [draft pull request #3](https://github.com/1919013/adguard-vpn-desktop/pull/3).

Run headless checks with:

```sh
python -m compileall -q core modules services ui main.py
python -m unittest discover -s tests -v
```

GitHub Actions runs these checks on pushes and pull requests. Passing CI does not replace runtime testing on Debian/Cinnamon.

## Project layout

- `core/` — application logic.
- `modules/` — feature tabs and controllers.
- `services/` — system integrations and state handling.
- `ui/` — GTK interface.
- `i18n/` — planned translations.
- `tests/` — headless regression tests.

## Test installation from a Debian package

The `release/0.2.0` branch has a GitHub Actions workflow that builds a test `.deb` package. It contains the GUI wrapper but **does not install AdGuard VPN CLI**. Install the CLI separately from the “Инфо ADGuard” tab.

This is a test candidate, not a stable release. Download the artifact from the **Artifacts** section of a successful [Build Debian package workflow run](https://github.com/1919013/adguard-vpn-desktop/actions/workflows/build-deb.yml?query=branch%3Arelease%2F0.2.0). Extract the artifact ZIP and install:

```sh
sudo apt install ./adguard-vpn-desktop_0.2.0~dev_all.deb
```

Launch from the applications menu or run `adguard-vpn-desktop`.

Remove the GUI wrapper with:

```sh
sudo apt remove adguard-vpn-desktop
```

Removing the GUI package does not remove AdGuard VPN CLI or its user settings. The package should be tested on Debian 13 with GTK 3 and NetworkManager.

## Updating the current Git checkout

For a clean clone with its upstream branch configured:

```sh
git pull --ff-only
```

For the default user installation created by the GUI:

```sh
cd ~/.local/share/adguard-vpn-desktop/app && git pull --ff-only
```

## License

This project is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See the complete terms in [`LICENSE`](LICENSE). Unless a file states otherwise, project contributions are offered under the same license.
