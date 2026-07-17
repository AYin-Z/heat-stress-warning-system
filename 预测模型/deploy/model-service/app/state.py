from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from redis.asyncio import Redis

from .schemas import DeviceState


class StateRepository:
    def __init__(self, redis_url: str, ttl_seconds: int):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds
        self._memory: dict[str, DeviceState] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.redis_available = False

    async def connect(self) -> None:
        try:
            await self.redis.ping()
            self.redis_available = True
        except Exception:
            self.redis_available = False

    async def close(self) -> None:
        await self.redis.aclose()

    def lock(self, device_id: str) -> asyncio.Lock:
        return self._locks[device_id]

    async def get(self, device_id: str) -> DeviceState:
        key = f"heatstress:device:{device_id}"
        if self.redis_available:
            try:
                raw = await self.redis.get(key)
                return DeviceState.model_validate_json(raw) if raw else DeviceState()
            except Exception:
                self.redis_available = False
        return self._memory.get(device_id, DeviceState()).model_copy(deep=True)

    async def put(self, device_id: str, state: DeviceState) -> None:
        key = f"heatstress:device:{device_id}"
        if self.redis_available:
            try:
                await self.redis.set(key, state.model_dump_json(), ex=self.ttl_seconds)
                return
            except Exception:
                self.redis_available = False
        self._memory[device_id] = state.model_copy(deep=True)

