# Command allowlists

One YAML per role. The SSH executor regex-validates every argv against `commands[].match`. Unmatched = rejected.

## Schema

```yaml
role: <role-id>
mutating: false               # true requires fresh approval_id
targets: ["*"]                # or list of host globs: ["host-prod-*", "nas01.local"]
commands:
  - id: human-readable-id
    match: ^<full-argv regex, anchors implicit>$   # via re.fullmatch
    description: what it does and why it's safe
```

## Conventions

- `match` is matched against the joined argv (`" ".join(argv)`), case-sensitive, anchored.
- Use `[a-zA-Z0-9_.-]+` for free string slots (e.g. container names) — never `.+` or `.*`.
- For commands that take a target path, restrict the path explicitly: `/var/log/[a-zA-Z0-9_/.-]+`.
- If you find yourself wanting to allow a meta-character, you're allowing a class of commands too broad — split into separate entries.

## Per-role files

| File | Used by |
|---|---|
| `monitoring.yaml` | Monitoring agent (HTTP probes, metric reads — minimal SSH) |
| `linux-readonly.yaml` | Linux Administrator |
| `docker-readonly.yaml` | Docker Expert |
| `unifi-readonly.yaml` | Network Engineer (HTTP GET only via separate gateway) |
| `proxmox-readonly.yaml` | Proxmox agent |
| `nas-readonly.yaml` | NAS agent |
| `security-readonly.yaml` | Security Analyst |
| `commander.yaml` | Incident Commander (no shell tools — placeholder) |
| `rca.yaml` | RCA agent (no shell tools) |
| `remediation.yaml` | THE mutating allowlist |
| `verification.yaml` | Post-fix re-probes |
| `audit.yaml` | Audit writer |
