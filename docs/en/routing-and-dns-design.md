# Application routing and DNS: verified design basis

This document records only capabilities confirmed by the official AdGuard VPN CLI documentation and the limitations that must be tested before implementation.

## Confirmed official capabilities

### TUN

In TUN mode, AdGuard VPN creates a virtual interface and manages system routing. The default AUTO routing mode applies the tunnel system-wide; it is not an application selector.

### Custom SCRIPT routing mode

The CLI supports three tunnel routing modes: NONE, AUTO, and SCRIPT.

- NONE brings up TUN without changing the routing table.
- AUTO manages system routes automatically.
- SCRIPT executes a user-supplied script when tunnel state changes.

Enable it with `adguardvpn-cli config set-tun-routing-mode SCRIPT`.

Create the script template with correct permissions using `adguardvpn-cli config create-route-script`.

The official Linux example uses the first script argument as the TUN interface name (`INTERFACE="$1"`) and demonstrates adding and deleting IP routes.

**Not yet established and must be tested against supported CLI versions:** exact invocation semantics on connect, disconnect, reconnect, and failure; call ordering guarantees; execution environment and privileges; and behavior when the script exits unsuccessfully. Production logic must not assume that connect and disconnect invoke the script with identical arguments.

### DNS through AdGuard VPN CLI itself

The official documentation describes:

- `adguardvpn-cli config set-dns <server_address>` to set the DNS upstream;
- `adguardvpn-cli config set-change-system-dns on|off` to enable or disable system DNS changes.

These settings are inactive in SOCKS mode. In TUN mode, the CLI can manage system DNS. This is the preferred first candidate for DNS integration because it avoids directly editing user NetworkManager profiles.

**Not established until tested on the target CLI version:** how to reset an explicitly configured DNS upstream to its factory Default value, and whether an unset/default state can be safely read and restored. Do not pass the word `Default` to `set-dns` or promise automatic restoration without verification.

## Safe implementation plan

1. Implement read-only parsing of `adguardvpn-cli config show` for DNS upstream, Change system DNS, and Tunnel routing mode.
2. Save original values in a per-user backup with mode 0600; validate owner, format, version, and data integrity.
3. Permit DNS changes only after a backup exists and a supported restoration method has been verified.
4. Re-read CLI configuration after each change and compare it with the expected state.
5. Avoid modifying NetworkManager profiles for the primary DNS workflow unless proven necessary.
6. Test SCRIPT in an isolated environment and log invocations during connect, disconnect, reconnect, network loss, and CLI shutdown.
7. Design transactional route activation/deactivation only after the SCRIPT lifecycle contract is confirmed.
8. Separately validate cgroup v2, nftables, fwmark, and policy routing for per-app routing; cover IPv4, IPv6, DNS, local networks, rollback, and crash recovery.
9. Do not expose per-app routing toggles before successful integration tests.

## Important limitations

- SOCKS5 lets an application use the proxy only if that application supports SOCKS. This is not equivalent to transparent routing for arbitrary processes.
- `site-exclusions` are domain/site exclusions, not a list of local applications.
- Unit tests do not prove real routing correctness or absence of DNS/IPv6 leaks.
- Real user network profile names and identifiers must never appear in public source, tests, or documentation.

## Official references

- [AdGuard VPN for Linux: Settings](https://adguard-vpn.com/kb/adguard-vpn-for-linux/settings/)
- [Official AdGuard VPN CLI repository](https://github.com/AdguardTeam/AdGuardVPNCLI)
