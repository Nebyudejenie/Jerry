# Production Vault config (file backend; swap for Raft in HA).
ui = true
disable_mlock = false
api_addr     = "https://vault.example.local:8200"
cluster_addr = "https://vault.example.local:8201"

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/vault/config/vault.crt"
  tls_key_file  = "/vault/config/vault.key"
  tls_min_version = "tls13"
}

# Auto-unseal via cloud KMS (example: AWS):
# seal "awskms" {
#   region     = "us-east-1"
#   kms_key_id = "arn:aws:kms:..."
# }
