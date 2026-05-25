# Scenario: Container stopped

## Detection
- Monitoring agent gets non-200 from HTTP probe OR expected body absent.
- Heartbeat workflow writes `down` to `monitoring.status`.

## Investigation (read-only, by Docker Expert agent)
```bash
docker ps -a --format '{{.Names}}\t{{.Status}}'                    # is it Exited?
docker inspect <name> --format '{{.State.ExitCode}}|{{.State.Error}}'
docker logs <name> --tail 50 --timestamps
```

## Decision matrix
| Exit code | Likely cause | Proposed remediation |
|---|---|---|
| 0   | clean stop (someone stopped it) | `docker start <name>` |
| 1   | application error | inspect logs; restart only if cause is transient |
| 137 | OOM-killed | check host memory; restart with note |
| 139 | segfault | escalate to human; do NOT auto-restart |

## Remediation (requires approval)
```bash
docker start <name>
```

## Rollback
```bash
docker stop <name>
```

## Verification (Verification agent)
```bash
curl -s -o /dev/null -w '%{http_code}' http://<endpoint>/
docker ps --filter name=<name> --format '{{.Status}}'
```
Verdict `green` requires both: HTTP 200 + container `Up`.
