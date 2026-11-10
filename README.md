# ADGuard VPN Desktop

Open-source graphical desktop interface for AdGuard VPN CLI on Linux.

> Work in progress. This repository currently contains a scaffold, not a replacement for the installed application.

## Goals
- Connect to and disconnect from AdGuard VPN CLI.
- Browse and select VPN locations.
- Carefully tested per-application routing (split tunneling).
- DNS management with explicit safeguards, backups and leak checks.
- Diagnostics, settings and contextual help.
- Russian and English localization.

## Architecture
- `core/`: application logic and orchestration.
- `modules/`: user-facing features.
- `services/`: DNS, backup and NetworkManager operations.
- `ui/`: GTK interface.
- `i18n/`: translations.
- `docs/`: documentation.
- `tests/`: automated tests.

The UI must not execute operating-system commands directly. System operations are isolated behind core/service interfaces.

## Safety
- Never change active NetworkManager profiles without explicit user consent.
- DNS changes require a validated backup and tested rollback.
- Develop DNS behavior on a dedicated test profile first.
- Do not claim split tunneling is ready until routing, DNS and IPv6 are verified.
- Never commit credentials, private keys or local DNS snapshots.

## Status
Current development branch: `feature/large-feature-blocks` (see pull request #2).

Implemented on this branch:
- AdGuard VPN CLI connection controls and server selection.
- AdGuard VPN CLI management: official install/update checks, connect/disconnect, user cache/data cleanup, CLI and GUI autostart.
- Dynamic network interface discovery and CLI outbound-interface override.
- Per-app launchers through AdGuard VPN CLI SOCKS5 + proxychains-ng. This is a TCP proxy launcher approach, not native per-process TUN routing. UDP/QUIC and sandboxed Flatpak/Snap apps are not guaranteed.
- Browser-based help and an explicit unofficial-project disclaimer.

Still pending:
- Full production DNS design; current DNS manager is intentionally restricted to test profiles.
- Full Russian/English localization.
- Runtime verification on Debian 13/Cinnamon and packaging/release validation.

For the per-app proxy feature on Debian, install `proxychains4`: `sudo apt install proxychains4`.
Then switch AdGuard VPN CLI to SOCKS mode: `adguardvpn-cli config set-mode SOCKS`.
Reconnect after changing the mode. SOCKS mode requires each selected application to be launched through its generated VPN launcher.

## License
No license has been selected yet. Until one is added, this repository does not grant permission to redistribute or modify the project.

See [README.ru.md](README.ru.md) for Russian.
