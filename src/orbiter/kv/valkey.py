"""Valkey-backed KeyValueStore.

compare_and_delete must be atomic server-side; a GET-then-DEL from the client
has exactly the race the fenced lease exists to prevent, so it is a Lua script.
"""

from __future__ import annotations

import math
from typing import cast

import redis.asyncio as aioredis

_COMPARE_AND_DELETE = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


class ValkeyKV:
    def __init__(self, url: str) -> None:
        self._client: aioredis.Redis = aioredis.Redis.from_url(url, decode_responses=True)
        self._cad = self._client.register_script(_COMPARE_AND_DELETE)

    async def get(self, key: str) -> str | None:
        # decode_responses=True guarantees str at runtime; redis-py types it as bytes|str.
        return cast(str | None, await self._client.get(key))

    async def set_if_absent(self, key: str, value: str, ttl_s: float) -> bool:
        ok = await self._client.set(key, value, nx=True, px=max(1, math.ceil(ttl_s * 1000)))
        return bool(ok)

    async def incr(self, key: str) -> int:
        value: int = await self._client.incr(key)
        return value

    async def compare_and_delete(self, key: str, expected: str) -> bool:
        deleted = await self._cad(keys=[key], args=[expected])
        return bool(deleted)

    async def aclose(self) -> None:
        await self._client.aclose()
