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

`services/split_tunnel_privileged.py` now adds a narrow root-side apply/remove implementation. It accepts only a validated scope name, cgroup level, route table, mark and priority; it does not accept arbitrary shell commands or nft snippets. It checks for an existing nftables table and conflicting `ip rule` entries, writes a root-owned state record, creates the nftables table first, adds the policy rule second, and removes the newly-created nftables table if the second step fails. Removal reconstructs the exact policy rule from validated state and requires the nftables ownership comment before deleting the table.

The helper's cleanup path now inspects the live `ip -j rule show` output, removes only the exact rule recorded in its root-owned state, verifies that the rule is gone, and retains state / nftables objects if rule removal fails. This avoids silently losing the recovery record while a policy rule may still be active.

This helper is **not yet connected to the GTK interface or installed through a polkit policy/package**. It is not safe to invoke manually as a user-facing feature yet. DNS policy, verification of the actual AdGuard CLI SCRIPT lifecycle, endpoint protection, reconnect cleanup and real Debian/Flatpak tests remain blockers. The feature is therefore still not operational.

## Desktop application catalog

`services/desktop_applications.py` scans standard system and per-user desktop-entry locations, including Flatpak exports. It honours user-level overrides and hidden entries, parses `Exec` into argv without invoking a shell, identifies Flatpak launchers and flags D-Bus-activatable entries. `modules/applications.py` presents the catalog in GTK with case-insensitive prefix filtering, checkboxes and an explicit absolute-path field for executables outside the desktop catalog. Custom paths must point to an existing executable file. `services/application_selection.py` stores selected desktop IDs and custom executable paths atomically under the user's XDG config directory (default `~/.config/adguard-vpn-desktop/applications.json`, mode `0600`). This is saved intent only: the UI does not yet launch applications through the routing scope or apply routing rules; this is intentionally stated in the interface.

Flatpak applications that use D-Bus activation or single-instance behavior must be fully stopped before a future scoped launch. Otherwise the session bus may activate an already-running process outside the selected cgroup. The catalog flag is informational and does not solve that lifecycle issue.

## Required verification before enabling changes

- cgroup v2 and delegated user systemd scopes work on supported Debian/Cinnamon sessions;
- nftables `socket cgroupv2 level N NAME` matches the selected systemd scope on IPv4 and IPv6 output;
- selected native and Flatpak applications route through the VPN (Flatpak single-instance/D-Bus activation must not reuse an already-running unscoped process);
- unselected applications retain direct routing;
- DNS and QUIC/UDP follow the same selection;
- the VPN control connection and endpoint never enter a routing loop;
- disconnect, reconnect, app restart, logout and crash restore clean state;
- a failed apply automatically rolls back every rule and nftables object.
