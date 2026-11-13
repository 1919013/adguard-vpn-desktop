# ADGuard VPN Desktop

An independent desktop GUI for **AdGuard VPN CLI** on Linux. This project is not developed, endorsed, or supported by AdGuard.

> Development status: feature branch under review. Runtime validation on target desktop systems and release packaging are still pending.

## Current feature set

- VPN CLI connection controls and server/location selection.
- AdGuard VPN CLI management: installation detection, official install/update workflow, status, connect/disconnect, cache and user-data cleanup, and separate CLI/GUI autostart controls.
- Dynamic network-interface discovery and the AdGuard VPN CLI outbound-interface override. Personal NetworkManager profile names are not hard-coded.
- A website-exclusions tab using the CLI's native General and Selective lists.
- Separate application launchers using SOCKS5 and `proxychains4` (a limited compatibility mechanism).
- An experimental planner for selected-app TUN routing based on cgroup v2, systemd, and nftables. It is not yet connected to the Apply UI and does not change network settings.
- Browser-based help with an explicit unofficial-project disclaimer.
- A DNS tab in a deliberately restricted test-only mode.

## Split tunneling

### Websites

The website-exclusions tab controls the native CLI feature:
- **General** — listed websites bypass the VPN.
- **Selective** — only listed websites use the VPN.

There is one domain list and one active mode; changing the mode changes how that same list is applied. Editing the list does not silently switch modes. The website list is independent from app selection. See the [official Linux settings documentation](https://adguard-vpn.com/kb/en/adguard-vpn-for-linux/settings/).

### Applications

Current SOCKS5/proxy launchers are not full per-process split tunneling; interception is not guaranteed for every app or protocol. An experimental TUN-routing foundation has been added using a dedicated systemd cgroup, nftables socket-cgroup matching, and a separate routing table. At this stage, only the planner and headless tests exist; UI integration, connection/disconnection lifecycle handling, and the “all apps except selected” mode remain unfinished. Do not manually apply experimental rules to a production network before dedicated validation.

## DNS

The current DNS manager is a safety test harness restricted to two explicitly allowlisted test profiles. It refuses active test profiles and refuses writes unless AdGuard VPN TUN status is confirmed. It does not modify ordinary user NetworkManager profiles. This is not production DNS management or a DNS leak test.

## Network interfaces

The interface tab discovers current non-loopback, non-tunnel devices and applies the documented `adguardvpn-cli config set-bound-if-override` setting. It does not edit NetworkManager connection profiles. The CLI setting accepts one interface; clearing the selection restores automatic interface choice.

## Development and checks

The active development branch is `feature/large-feature-blocks`; see [pull request #2](https://github.com/1919013/adguard-vpn-desktop/pull/2).

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

No license has been selected yet. Until a license is added, the repository does not grant permission to redistribute or modify the project.
