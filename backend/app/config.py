from __future__ import annotations

from functools import lru_cache
from typing import Any

import hvac
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_origin: str = "http://localhost:8000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "compass"
    postgres_admin_user: str = "postgres"

    redis_url: str = "redis://redis:6379/0"

    vault_addr: str = "http://vault:8200"
    vault_token: SecretStr = SecretStr("dev-only-root-token")
    vault_mount: str = "secret"
    vault_secret_path: str = "compass"

    upload_root: str = "/app/.runtime/uploads"
    storage_backend: str = "s3"  # "s3" (MinIO) or "local"
    s3_endpoint_url: str = "http://minio:9000"
    s3_bucket: str = "compass-documents"
    cache_ttl_search_seconds: int = 300
    cache_ttl_dash_seconds: int = 180
    cache_ttl_embed_seconds: int = 86400
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"


class RuntimeSettings(BaseModel):
    app_env: str
    app_origin: str
    api_host: str
    api_port: int
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_admin_user: str
    postgres_password: SecretStr
    compass_app_password: SecretStr
    compass_writer_password: SecretStr
    redis_url: str
    openai_api_key: SecretStr
    jwt_signing_key: SecretStr
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    vault_addr: str
    vault_mount: str
    vault_secret_path: str
    upload_root: str
    storage_backend: str
    s3_endpoint_url: str
    s3_bucket: str
    cache_ttl_search_seconds: int
    cache_ttl_dash_seconds: int
    cache_ttl_embed_seconds: int
    reranker_model: str
    openai_chat_model: str
    openai_embedding_model: str


def _read_vault_secret(bootstrap: BootstrapSettings) -> dict[str, Any]:
    client = hvac.Client(
        url=bootstrap.vault_addr,
        token=bootstrap.vault_token.get_secret_value(),
    )
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed.")

    response = client.secrets.kv.v2.read_secret_version(
        mount_point=bootstrap.vault_mount,
        path=bootstrap.vault_secret_path,
    )
    return response["data"]["data"]


@lru_cache(maxsize=1)
def get_bootstrap_settings() -> BootstrapSettings:
    return BootstrapSettings()


@lru_cache(maxsize=1)
def get_settings() -> RuntimeSettings:
    bootstrap = get_bootstrap_settings()
    vault_data = _read_vault_secret(bootstrap)

    return RuntimeSettings(
        app_env=bootstrap.app_env,
        app_origin=bootstrap.app_origin,
        api_host=bootstrap.api_host,
        api_port=bootstrap.api_port,
        postgres_host=bootstrap.postgres_host,
        postgres_port=bootstrap.postgres_port,
        postgres_db=bootstrap.postgres_db,
        postgres_admin_user=bootstrap.postgres_admin_user,
        postgres_password=SecretStr(vault_data["postgres_password"]),
        compass_app_password=SecretStr(vault_data["compass_app_password"]),
        compass_writer_password=SecretStr(vault_data["compass_writer_password"]),
        redis_url=bootstrap.redis_url,
        openai_api_key=SecretStr(vault_data["openai_api_key"]),
        jwt_signing_key=SecretStr(vault_data["jwt_signing_key"]),
        s3_access_key=SecretStr(vault_data.get("s3_access_key", "compass-minio")),
        s3_secret_key=SecretStr(vault_data.get("s3_secret_key", "compass-minio-secret")),
        vault_addr=bootstrap.vault_addr,
        vault_mount=bootstrap.vault_mount,
        vault_secret_path=bootstrap.vault_secret_path,
        upload_root=bootstrap.upload_root,
        storage_backend=bootstrap.storage_backend,
        s3_endpoint_url=bootstrap.s3_endpoint_url,
        s3_bucket=bootstrap.s3_bucket,
        cache_ttl_search_seconds=bootstrap.cache_ttl_search_seconds,
        cache_ttl_dash_seconds=bootstrap.cache_ttl_dash_seconds,
        cache_ttl_embed_seconds=bootstrap.cache_ttl_embed_seconds,
        reranker_model=bootstrap.reranker_model,
        openai_chat_model=bootstrap.openai_chat_model,
        openai_embedding_model=bootstrap.openai_embedding_model,
    )
