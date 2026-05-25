# Scenario: Disk pressure

## Detection
- Prometheus `DiskPressure` alert (<15% free) OR `df -hT` shows >85% used on a data volume.
- Symptom path: container build fails / image pull fails / `journalctl` reports `No space left`.

## Investigation (Linux Admin agent, read-only)
```bash
df -hT
du -sh /var /home /opt /tmp
docker system df            # docker disk usage if relevant
journalctl --disk-usage     # journal occupies?
ls -lh /var/log
```

## Decision matrix
| Top offender | Proposed remediation | Blast radius |
|---|---|---|
| Docker overlay images | `docker system prune -f` | low — only unused |
| Docker images (tagged but unused) | `docker image prune -af` | low |
| systemd journal | `journalctl --vacuum-size=2G` | low — logs trimmed |
| `/var/log/<service>` huge | `logrotate -f /etc/logrotate.conf` | low |
| Application data (e.g., Postgres) | ESCALATE — needs human |  |

## Remediation (gated)
Workflow: [workflows/remediation/disk-pressure.json](../../workflows/remediation/disk-pressure.json).
Sequence:
1. Baseline `df -hT` (audit).
2. Approval → `docker system prune -f`.
3. Wait 30s.
4. Post-prune `df -hT`.
5. If still >85% → escalate to `journalctl --vacuum-size=2G` (second approval).

## Verification
```bash
df -hT                                 # target volume <75% used
docker system df                       # reclaimed bytes > 0
```
Verdict `green` requires both rows pass.

## Recurrence prevention
- Set a Prometheus rule for trend (>1%/day growth on `/var/lib/docker`).
- Schedule weekly `docker system prune -af --filter "until=168h"`.
- Cap container `log-opts` (max-size + max-file) in `/etc/docker/daemon.json`.
