# Scenario: VM in unexpected state (Proxmox)

## Detection
- `proxmox-health` workflow reports a VM with `status` ≠ expected (e.g., `stopped` when monitoring expects `running`).
- Quorum could also be degraded — check that FIRST; never `qm start` during quorum loss.

## Investigation (Proxmox agent, read-only)
```bash
pvecm status                                                  # ← do this first
pvesh get /nodes/<node>/qemu/<vmid>/status/current            # live VM status
qm config <vmid>                                              # VM config — is HA-managed?
tail -n 100 /var/log/pve/tasks/index                          # recent task log
```

## Decision matrix
| VM state | Quorum | Proposed | Blast radius |
|---|---|---|---|
| `stopped` (clean) | ok | `qm start <vmid>` | low |
| `stopped` (after crash, repeated) | ok | escalate — investigate `lock`, qemu logs | — |
| `paused` | ok | `qm resume <vmid>` *(future allowlist entry)* | low |
| `running` but unresponsive | ok | `qm reboot <vmid>` | medium |
| Any | degraded | DO NOT TOUCH — escalate to human | — |

## Remediation (gated)
Workflow: [workflows/remediation/vm-recover.json](../../workflows/remediation/vm-recover.json).
Always preflights with a read of `status/current`. If `running` → no-op. If `unknown` → escalate to human.

## Verification
```bash
pvesh get /nodes/<node>/qemu/<vmid>/status/current            # status: running
# Then probe the VM's own service endpoint (HTTP / SSH ping)
```
Verdict `green` requires both: Proxmox reports `running` AND the VM's own service is reachable.

## Recurrence prevention
- If the VM is HA-managed, document who owns the underlying workload — auto-start may mask app-level bugs.
- Add a Prometheus check on the in-guest service (not just the hypervisor state).
- Capture `qemu-guest-agent ping` in the monitoring target to detect "running but hung".
