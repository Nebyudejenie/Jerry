# Scenario: Port conflict (another process owns the container's port)

## Detection
- Container starts then exits with `bind: address already in use` in logs.
- HTTP probe to expected port returns wrong content (someone else is serving on that port).

## Investigation
```bash
docker logs <name> --tail 50                        # look for "bind"
ss -tlnp sport = :<port>                            # who owns the port?
```

## Decision matrix
| Owner found | Proposed remediation |
|---|---|
| A known sibling container (e.g. an old copy) | Stop the sibling: `docker stop <other>` |
| An ad-hoc process (e.g. `python -m http.server`) | Escalate: human decision (who started it?) |
| A system service | Escalate: needs an architecture change |

## Hard rule
Terry NEVER `kill`s unknown processes. The port conflict could be a deliberate test or a sibling service.

## Verification
After remediation:
```bash
ss -tlnp sport = :<port>                            # expect ONE listener, the target container
curl -s -o /dev/null -w '%{http_code}' http://localhost:<port>/
```
