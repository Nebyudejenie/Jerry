# `secrets/` — host-side material

Bind-mounted into containers read-only. **Never commit anything here except `.gitkeep` and this README.**

## `secrets/ssh/`

Holds the SSH key Terry uses to reach managed hosts.

### First-time setup

```bash
# Generate a dedicated key (NOT your personal key)
ssh-keygen -t ed25519 -N "" -f secrets/ssh/id_terry -C "terry@$(hostname)"

# Sign with Vault's SSH CA (production) or copy id_terry.pub to each target's
# /home/terry/.ssh/authorized_keys (homelab)

# known_hosts: pin each target you'll reach
for host in host1.local host2.local nas.local; do
  ssh-keyscan -t ed25519 "$host" >> secrets/ssh/known_hosts
done

# Permissions — the toolbox container reads as a non-root user;
# files must be world-readable but the dir is r-x.
chmod 700 secrets/ssh
chmod 644 secrets/ssh/id_terry secrets/ssh/known_hosts
chmod 644 secrets/ssh/id_terry.pub
```

### Vault-signed certs (production)

After running the Vault setup in [infra/vault/README.md](../infra/vault/README.md):

```bash
vault write -field=signed_key terry-ssh/sign/terry-ops \
  public_key=@secrets/ssh/id_terry.pub > secrets/ssh/id_terry-cert.pub
```

The toolbox SSH executor will prefer the cert over the raw key when both are present (it passes both with `-i id_terry -i id_terry-cert.pub`, OpenSSH picks the matching cert).

## What lives here at runtime

```
secrets/
├── README.md
└── ssh/
    ├── .gitkeep
    ├── id_terry            (private, never commit)
    ├── id_terry.pub        (public, fine to commit if you want)
    ├── id_terry-cert.pub   (Vault-signed, expires every 5m)
    └── known_hosts         (target host keys, pinned)
```

`.gitignore` excludes everything except `README.md` and `.gitkeep`.
