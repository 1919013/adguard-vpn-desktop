#!/usr/bin/env bash
# Read-only preflight for ADGuard VPN Desktop split-tunnel testing.
# Does not install packages, alter DNS, add/delete routes or ip rules, or apply nft rules.
set -u

section() { printf '\n===== %s =====\n' "$1"; }
run() {
    printf '\n$'
    printf ' %q' "$@"
    printf '\n'
    "$@" 2>&1 || true
}

section "System"
run cat /etc/os-release
run uname -a
run systemd --version
printf 'cgroup filesystem: '
stat -fc '%T' /sys/fs/cgroup 2>&1 || true
printf 'current UID: %s\n' "$(id -u)"
printf 'user systemd state: '
systemctl --user is-system-running 2>&1 || true

section "Split-tunnel systemd units"
for unit in app-adguard-vpn.slice adguard-vpn-desktop-watchdog.service; do
    printf '%s: ' "$unit"
    systemctl --user show "$unit" -p LoadState -p ActiveState -p ControlGroup 2>&1 || true
done
printf 'installed slice unit: '
test -r /usr/lib/systemd/user/app-adguard-vpn.slice && echo yes || echo no
printf 'installed watchdog unit: '
test -r /usr/lib/systemd/user/adguard-vpn-desktop-watchdog.service && echo yes || echo no

section "Kernel routing and nftables (read-only inspection)"
run nft --version
run ip -Version
run ip -j rule show
run ip -4 route show table all
run ip -6 route show table all

section "nftables cgroupv2 syntax probe (check-only; does not apply rules)"
if command -v nft >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    sudo nft --check -f - <<'NFT'
add table inet adguard_vpn_desktop_probe
add chain inet adguard_vpn_desktop_probe app_output { type route hook output priority mangle; policy accept; }
add rule inet adguard_vpn_desktop_probe app_output socket cgroupv2 level 5 app-adguard-vpn.slice meta mark set 0xad61
add chain inet adguard_vpn_desktop_probe app_guard { type filter hook output priority filter; policy accept; }
add rule inet adguard_vpn_desktop_probe app_guard meta mark 0xad61 oifname != "tun0" drop
delete table inet adguard_vpn_desktop_probe
NFT
    printf 'NOTE: nft --check validates the batch without committing it.\n'
else
    echo "SKIPPED: nft or sudo is unavailable."
fi

section "Polkit"
run pkexec --version
run pkaction --version
printf 'helper: '
test -x /usr/libexec/adguard-vpn-desktop-helper && echo installed || echo missing
printf 'policy: '
test -r /usr/share/polkit-1/actions/org.adguard-vpn-desktop.policy && echo installed || echo missing

section "AdGuard VPN CLI"
if command -v adguardvpn-cli >/dev/null 2>&1; then
    run adguardvpn-cli --version
    run adguardvpn-cli status
    run adguardvpn-cli config show
else
    echo "adguardvpn-cli: not found"
fi
printf '\nCLI DNS file (if present):\n'
if test -r "$HOME/.local/share/adguardvpn-cli/resolv.conf"; then
    sed -n '1,20p' "$HOME/.local/share/adguardvpn-cli/resolv.conf"
else
    echo "not found"
fi
printf '\nActive resolver configuration:\n'
if test -r /etc/resolv.conf; then
    sed -n '1,30p' /etc/resolv.conf
else
    echo "/etc/resolv.conf is not readable"
fi

section "Flatpak targets"
if command -v flatpak >/dev/null 2>&1; then
    flatpak list --app --columns=application,name 2>&1 | grep -Ei 'chrome|telegram' || true
else
    echo "flatpak: not installed"
fi

section "End"
echo "This report is diagnostic only. It does not prove real application traffic is routed through the VPN."
