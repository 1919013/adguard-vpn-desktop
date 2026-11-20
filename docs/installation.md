# Installation and test build

This repository is an independent GTK wrapper for the official **AdGuard VPN CLI**. It is not an AdGuard product and does not bundle the VPN CLI.

## Requirements

- Debian-based Linux desktop with GTK 3 and PyGObject.
- Python 3.
- NetworkManager, iproute2, nftables and systemd user services for the advanced routing features.
- The official `adguardvpn-cli` installed and authenticated separately.

On Debian 13, install the GUI runtime dependencies with:

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 network-manager iproute2 nftables systemd
```

Install and sign in to AdGuard VPN CLI using the official AdGuard instructions.

## Get the current development build

The 0.2.0 branch is still a draft and has not been released. To inspect it without replacing an existing installation:

```sh
git clone --branch release/0.2.0 https://github.com/1919013/adguard-vpn-desktop.git
cd adguard-vpn-desktop
python3 -m compileall -q core modules services ui main.py
python3 -m unittest discover -s tests -v
python3 main.py
```

Do not run the DNS write actions on everyday NetworkManager profiles; the current DNS implementation is restricted to dedicated test profiles. Per-application routing and Flatpak traffic still require runtime validation on the target desktop.

A packaged installer and stable release will be published only after the Debian/Cinnamon integration checks pass.
