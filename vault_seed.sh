#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-dev-only-root-token}"
VAULT_MOUNT="${VAULT_MOUNT:-secret}"
VAULT_SECRET_PATH="${VAULT_SECRET_PATH:-compass}"

OPENAI_API_KEY="${OPENAI_API_KEY:-replace-me}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
COMPASS_APP_PASSWORD="${COMPASS_APP_PASSWORD:-compass_app_password}"
COMPASS_WRITER_PASSWORD="${COMPASS_WRITER_PASSWORD:-compass_writer_password}"
JWT_SIGNING_KEY="${JWT_SIGNING_KEY:-replace-me-jwt-signing-key}"
S3_ACCESS_KEY="${MINIO_ROOT_USER:-compass-minio}"
S3_SECRET_KEY="${MINIO_ROOT_PASSWORD:-compass-minio-secret}"

export VAULT_ADDR
export VAULT_TOKEN

if command -v vault >/dev/null 2>&1; then
  vault kv put "${VAULT_MOUNT}/${VAULT_SECRET_PATH}" \
    openai_api_key="${OPENAI_API_KEY}" \
    postgres_password="${POSTGRES_PASSWORD}" \
    compass_app_password="${COMPASS_APP_PASSWORD}" \
    compass_writer_password="${COMPASS_WRITER_PASSWORD}" \
    jwt_signing_key="${JWT_SIGNING_KEY}"
else
  docker exec \
    -e VAULT_ADDR="http://127.0.0.1:8200" \
    -e VAULT_TOKEN="${VAULT_TOKEN}" \
    -e OPENAI_API_KEY="${OPENAI_API_KEY}" \
    -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    -e COMPASS_APP_PASSWORD="${COMPASS_APP_PASSWORD}" \
    -e COMPASS_WRITER_PASSWORD="${COMPASS_WRITER_PASSWORD}" \
    -e JWT_SIGNING_KEY="${JWT_SIGNING_KEY}" \
    compass-vault-1 \
    sh -lc "vault kv put \"${VAULT_MOUNT}/${VAULT_SECRET_PATH}\" \
      openai_api_key=\"\$OPENAI_API_KEY\" \
      postgres_password=\"\$POSTGRES_PASSWORD\" \
      compass_app_password=\"\$COMPASS_APP_PASSWORD\" \
      compass_writer_password=\"\$COMPASS_WRITER_PASSWORD\" \
      jwt_signing_key=\"\$JWT_SIGNING_KEY\""
fi

printf 'Seeded Vault path %s/%s\n' "${VAULT_MOUNT}" "${VAULT_SECRET_PATH}"

# S3/MinIO credentials are merged in with `kv patch` so this can be run without overwriting an
# existing OpenAI key (e.g. ./vault_seed.sh after the key was set out of band).
if command -v vault >/dev/null 2>&1; then
  vault kv patch "${VAULT_MOUNT}/${VAULT_SECRET_PATH}" \
    s3_access_key="${S3_ACCESS_KEY}" \
    s3_secret_key="${S3_SECRET_KEY}" || true
else
  docker exec \
    -e VAULT_ADDR="http://127.0.0.1:8200" \
    -e VAULT_TOKEN="${VAULT_TOKEN}" \
    -e S3_ACCESS_KEY="${S3_ACCESS_KEY}" \
    -e S3_SECRET_KEY="${S3_SECRET_KEY}" \
    compass-vault-1 \
    sh -lc "vault kv patch \"${VAULT_MOUNT}/${VAULT_SECRET_PATH}\" \
      s3_access_key=\"\$S3_ACCESS_KEY\" \
      s3_secret_key=\"\$S3_SECRET_KEY\"" || true
fi
printf 'Patched S3 credentials into Vault path %s/%s\n' "${VAULT_MOUNT}" "${VAULT_SECRET_PATH}"
