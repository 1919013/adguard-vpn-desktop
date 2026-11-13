# ADGuard VPN Desktop

An independent open-source desktop GUI for **AdGuard VPN CLI** on Linux. This project is not developed, endorsed, or supported by AdGuard.

> Development status: feature branch under review. Runtime validation on target desktop systems and release packaging are still pending.

## Current feature set

- VPN CLI connection controls and server/location selection.
- AdGuard VPN CLI information and management: detect installation, official install/update workflow, status, connect/disconnect, cache and user-data cleanup, and separate CLI/GUI autostart controls.
- Dynamic network-interface discovery and the AdGuard VPN CLI outbound-interface override. The interface list is detected at runtime; personal NetworkManager profile names are not hard-coded. The CLI currently supports one selected outbound interface.
- Application launchers through AdGuard VPN CLI SOCKS5 mode and `proxychains4`. The feature creates separate launchers and does not replace original desktop entries or system routes.
- Browser-based help with an explicit unofficial-project disclaimer.
- A DNS tab in a deliberately restricted test-only mode.

## Important limitations

### Per-application routing

Linux AdGuard VPN CLI does not expose a native per-process TUN selector. The current application-routing feature is a SOCKS5 + `proxychains4` launcher, not native per-process TUN routing. It requires SOCKS mode and a working local SOCKS listener. Proxy interception is not guaranteed for every application or protocol; UDP/QUIC behavior depends on application support. Flatpak and Snap launchers are marked unsupported.

On Debian, install the dependency with:

```sh
sudo apt install proxychains4
adguardvpn-cli config set-mode SOCKS
```

Reconnect the VPN after changing its mode. The generated launchers are separate entries labelled “via AdGuard VPN”.

### DNS

The current DNS manager is a safety test harness restricted to two explicitly allowlisted test profile names. It refuses active test profiles and refuses writes unless AdGuard VPN TUN status is confirmed. It does not modify ordinary user NetworkManager profiles. This is not production DNS management and not a DNS leak test.

### Network interfaces

The interface tab discovers current non-loopback, non-tunnel devices at runtime and applies the documented `adguardvpn-cli config set-bound-if-override` setting. It does not edit NetworkManager connection profiles. The CLI setting accepts one interface; clearing the selection restores automatic interface choice.

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

## License

No license has been selected yet. Until a license is added, the repository does not grant permission to redistribute or modify the project.
