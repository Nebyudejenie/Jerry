# Vault configuration

The compose runs Vault in **dev mode** for homelab convenience. For production, replace with the file-backend or Raft config below.

## Dev mode (default)

Already wired in `docker-compose.yml`:

```yaml
vault:
  image: hashicorp/vault:latest
  environment:
    VAULT_DEV_ROOT_TOKEN_ID: ${VAULT_ROOT_TOKEN}
    VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
```

After first boot:
```bash
docker compose exec vault sh -c 'vault login $VAULT_DEV_ROOT_TOKEN_ID'
docker compose exec vault sh -c 'vault secrets enable -path=terry-kv kv-v2'
docker compose exec vault sh -c 'vault secrets enable -path=terry-ssh ssh'
docker compose exec vault sh -c 'vault write terry-ssh/config/ca generate_signing_key=true'
docker compose exec vault sh -c 'vault read -field=public_key terry-ssh/config/ca' \
  > infra/vault/terry-ssh-ca.pub
```

Distribute `terry-ssh-ca.pub` to every target host:
```bash
scp infra/vault/terry-ssh-ca.pub root@<host>:/etc/ssh/trusted-user-ca-keys.pem
# Then in /etc/ssh/sshd_config on each host:
#   TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pem
# Reload sshd.
```

Define the signing role:
```bash
docker compose exec vault sh -c 'vault write terry-ssh/roles/terry-ops \
  algorithm_signer=rsa-sha2-256 \
  allow_user_certificates=true \
  allowed_users=terry \
  default_user=terry \
  ttl=5m \
  max_ttl=5m \
  key_type=ca'
```

Now n8n SSH executor obtains a fresh 5-minute cert per call:
```bash
vault write -field=signed_key terry-ssh/sign/terry-ops public_key=@/path/to/terry.pub > terry-cert.pub
ssh -i terry-cert.pub -i terry terry@<host> -- '<command>'
```

## Production: file backend with auto-unseal

See `infra/vault/vault.hcl` (template). Replace dev-mode env vars with:
```yaml
volumes:
  - ./infra/vault/vault.hcl:/vault/config/vault.hcl:ro
command: server -config=/vault/config/vault.hcl
```
