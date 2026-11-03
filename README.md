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
Initial scaffold. Existing working code will be migrated in small, reviewable steps.

## License
No license has been selected yet. Until one is added, this repository does not grant permission to redistribute or modify the project.

See [README.ru.md](README.ru.md) for Russian.
