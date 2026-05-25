# Scenario: DNS resolution failure

## Detection
- HTTP probes fail with `name resolution` / `nodename nor servname provided`.
- `dig +short <name>` returns empty.

## Investigation (Linux Admin agent, read-only)
```bash
cat /etc/resolv.conf
dig +short example.com @127.0.0.53
dig +short example.com @1.1.1.1                  # bypass local resolver
ping -c 2 1.1.1.1                                # is upstream reachable at all?
systemctl status systemd-resolved                # if applicable
ss -tunap | grep :53                             # who is binding port 53?
```

## Decision matrix
| Symptom | Likely cause | Proposed |
|---|---|---|
| Local resolver works, upstream does not | upstream outage | wait + alert; no auto-action |
| Upstream works, local does not | systemd-resolved broken | `systemctl restart systemd-resolved` (gated) |
| `/etc/resolv.conf` empty / wrong | misconfig | ESCALATE — config drift, not auto-fix |
| 53 hijacked by another process | port conflict | ESCALATE — security review |
| All upstreams unreachable | full network outage | escalate to Network Engineer agent |

## Remediation (gated)
Allowlist entry: `systemctl restart systemd-resolved.service` (in `remediation.yaml`).
- Approval required (medium blast radius — DNS hiccup affects every other service for ~1s).

## Verification
```bash
dig +short example.com
ping -c 2 example.com
```
Verdict `green` requires both: dig returns ≥1 record AND ping resolves and succeeds.

## Recurrence prevention
- Add a `dns-self` probe to `monitoring.targets` that runs every minute.
- Alert if resolution latency p95 > 200ms (early warning before full failure).
- If using `systemd-resolved`, pin upstream DNS in `/etc/systemd/resolved.conf` rather than DHCP.
