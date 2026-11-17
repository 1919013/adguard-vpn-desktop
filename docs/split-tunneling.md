# Split tunneling

Per-application routing is implemented as an **experimental** feature. Passing unit tests does not prove that every desktop application or sandbox is routed correctly.

## Modes

- **Only selected applications through VPN** — applications started from generated launchers are placed in the managed user systemd slice and their socket traffic is marked for the AdGuard TUN route. Other applications keep the normal system route.
- **All applications through VPN except selected** — traffic from the current user systemd session is marked for the VPN; selected applications started from generated launchers receive the direct-route mark.

The implementation uses the AdGuard VPN CLI SCRIPT route hook, systemd user scopes, cgroup v2 socket matching, nftables, and dedicated IPv4/IPv6 policy-routing rules. It does not replace the main default route. Private, link-local, CGNAT and multicast destinations remain on the normal route for local-network access.

## Desktop entries and launchers

Applications are discovered from XDG application directories, including the user and system Flatpak export directories. Flatpak IDs are parsed from desktop Exec commands and launched as `flatpak run APP_ID` inside the generated scope. Snap is not supported.

The generated alternate launchers are separate from original desktop entries. Close already-running instances and start the application using its generated launcher after applying the policy. Reconnect AdGuard VPN after changing the route hook.

## Limitations

- Flatpak is discovered and launched inside the scope, but actual sandbox/DBus traffic routing must still be verified on the target desktop.
- Snap, raw/ICMP traffic and non-standard DNS resolver paths are not supported or not verified.
- DNS is not isolated per application. Requests from systemd-resolved are routed through the VPN in both modes.
- This feature has automated headless tests but has not yet passed integration testing on Debian 13/Cinnamon.

Do not treat this feature as production-ready until the target-system checks are complete.

## Safe removal

Disconnect the VPN before disabling the feature. The disable action removes only the project's managed rules and generated launchers, then restores the saved CLI route-script and routing-mode settings. The original application launchers are not deleted.
