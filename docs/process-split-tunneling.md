# Process-aware split tunneling on Linux

## Goal

Allow the user to choose desktop applications whose traffic should use AdGuard VPN CLI, including native packages and Flatpak applications. The choice must apply to the complete process tree, not merely to the first launcher process.

## Proposed Linux mechanism

1. Discover the active cgroup v2 hierarchy and the current AdGuard VPN TUN interface/routing configuration.
2. Launch each selected desktop application inside a dedicated transient **systemd user scope**. Child processes inherit the scope's cgroup membership. The same launch wrapper works for native executables and `flatpak run APP_ID`; Flatpak's host-side launcher and its descendants remain in the host cgroup hierarchy.
3. Use nftables' cgroup-v2 packet metadata match to set a reserved packet mark for packets created by that application scope.
4. Use an `ip rule` matching that mark to select a dedicated VPN routing table. The VPN table must contain a default route through the currently active AdGuard TUN interface.
5. Keep all other traffic on the normal host routing policy. DNS, IPv4, IPv6, QUIC/UDP, reconnects, and tunnel endpoint reachability must be covered by the same policy and explicit tests.

## Important routing-mode constraint

AdGuard VPN CLI documents TUN routing modes `AUTO`, `SCRIPT`, and `NONE`. `AUTO` is designed for system-wide routing. A selected-app-only design cannot simply add a marked rule on top of AUTO and assume unmarked traffic stays direct: AUTO may already route the default traffic through the VPN.

The integration must inspect the live `ip rule` and route tables and use the CLI's supported `SCRIPT` lifecycle hook (or another documented arrangement) to maintain a dedicated table. It must not change the user's routing mode automatically until it can back up the original configuration, install a rollback, and verify the external VPN endpoint route.

Official reference: https://adguard-vpn.com/kb/adguard-vpn-for-linux/settings/

## Current code in this repository

`services/process_split_tunnel.py` contains non-mutating primitives:
- prerequisite detection for cgroup v2, systemd user manager, nftables, iproute2 and AdGuard VPN CLI;
- a safe argv wrapper for native and Flatpak launch commands using a transient user scope;
- validated process cgroup lookup and cgroup-v2 ID discovery;
- a builder for nftables `socket cgroupv2 level N NAME` matching (not legacy `meta cgroup`), plus a policy-routing rule command.

`services/routing_inspector.py` reads IPv4/IPv6 route tables and policy rules, detects the active TUN interface, and discovers a VPN route-table number from live kernel state without assuming a fixed AdGuard table ID.

`services/split_tunnel_planner.py` builds a fail-closed plan only when the caller explicitly confirms SCRIPT mode and DNS policy readiness, one unambiguous VPN table exists, and both IPv4/IPv6 default routes are present. It checks mark conflicts, selects a free rule priority, and emits a candidate nftables route-output chain plus reversible `ip rule` add/delete commands. It does not execute the plan.

These are building blocks only. The module does **not** execute nftables/ip mutations, alter AdGuard CLI settings, edit desktop files, or claim that split tunneling is operational. A privileged helper with transactional apply/rollback, dynamic route-table discovery, DNS policy and reconnect handling is still required.

## Required verification before enabling changes

- cgroup v2 and delegated user systemd scopes work on supported Debian/Cinnamon sessions;
- nftables `meta cgroup` matches the actual cgroup ID on IPv4 and IPv6 output;
- selected native and Flatpak applications route through the VPN (Flatpak single-instance/D-Bus activation must not reuse an already-running unscoped process);
- unselected applications retain direct routing;
- DNS and QUIC/UDP follow the same selection;
- the VPN control connection and endpoint never enter a routing loop;
- disconnect, reconnect, app restart, logout and crash restore clean state;
- a failed apply automatically rolls back every rule and nftables object.
