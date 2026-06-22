from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from redis import Redis

from backend.app.config import get_settings


class CacheClient:
    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def build_key(namespace: str, *parts: Any, role: str | None = None, scope: str | None = None) -> str:
        normalized_parts = [namespace]
        if role:
            normalized_parts.append(role)
        if scope:
            normalized_parts.append(scope)
        normalized_parts.extend(str(part) for part in parts if part is not None)
        return ":".join(normalized_parts)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def normalize_text(value: str) -> str:
        return " ".join(value.split()).strip().lower()

    @classmethod
    def build_embedding_key(cls, model: str, text: str) -> str:
        return cls.build_key("emb", model, cls._digest(cls.normalize_text(text)))

    @classmethod
    def build_search_key(cls, role: str, scope: str, mode: str, query: str) -> str:
        return cls.build_key("search", role, scope, mode, cls._digest(cls.normalize_text(query)))

    @classmethod
    def build_dashboard_key(cls, catalog_id: str, scope: str, params: dict[str, Any]) -> str:
        params_json = json.dumps(params, sort_keys=True, separators=(",", ":"))
        return cls.build_key("dash", catalog_id, scope, cls._digest(params_json))

    def get_json(self, key: str) -> Any | None:
        payload = self.redis.get(key)
        if payload is None:
            return None
        return json.loads(payload)

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.redis.set(name=key, value=json.dumps(value), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self.redis.delete(key)

    def bust_namespace(self, namespace: str) -> int:
        cursor = 0
        deleted = 0
        pattern = f"{namespace}:*"
        while True:
            cursor, keys = self.redis.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                deleted += self.redis.delete(*keys)
            if cursor == 0:
                break
        return deleted

    def ping(self) -> bool:
        return bool(self.redis.ping())


@lru_cache(maxsize=1)
def get_cache() -> CacheClient:
    runtime = get_settings()
    return CacheClient(runtime.redis_url)
