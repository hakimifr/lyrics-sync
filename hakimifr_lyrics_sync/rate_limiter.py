# Copyright 2026 Firdaus Hakimi <hakimifr@proton.me>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Final, cast, override

from httpx import Headers

from hakimifr_lyrics_sync import live_info


class RateLimiter(ABC):
    @abstractmethod
    async def acquire(self): ...

    @abstractmethod
    def observe(self, response_headers: Headers) -> None: ...


class ItunesRateLimiter(RateLimiter):
    def __init__(self, max_calls: int, period: int):
        self.max_calls: Final[int] = max_calls
        self.period: Final[int] = period
        self.calls: list[float] = []
        self.lock: Final[asyncio.Lock] = asyncio.Lock()

    @override
    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                with live_info.waiting(
                    f"Sleeping for {sleep_time} s to avoid ratelimit from itunes API"
                ):
                    await asyncio.sleep(sleep_time)
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())

    @override
    def observe(self, response_headers: Headers) -> None:
        return


class BetterLyricsRateLimiter(RateLimiter):
    def __init__(self, backoff: float = 2.0):
        self.remaining: int | None = None
        self.backoff: Final[float] = backoff
        self.lock: Final[asyncio.Lock] = asyncio.Lock()

    @override
    async def acquire(self):
        async with self.lock:
            if self.remaining == 0:
                with live_info.waiting(
                    f"[magenta] Sleeping for {self.backoff} s due to BetterLyrics ratelimit[/magenta]"
                ):
                    await asyncio.sleep(self.backoff)

    @override
    def observe(self, response_headers: Headers):
        remaining = cast(str, response_headers.get("X-RateLimit-Remaining"))
        limit_type = cast(str, response_headers.get("X-RateLimit-Type"))
        if limit_type == "normal":
            self.remaining = int(remaining)


class LrcLibRateLimiter(RateLimiter):
    def __init__(self):
        self.ratelimit_time: int | None = None
        self.lock: Final[asyncio.Lock] = asyncio.Lock()

    @override
    async def acquire(self):
        async with self.lock:
            if self.ratelimit_time:
                with live_info.waiting(
                    f"[magenta] Sleeping for {self.ratelimit_time} s due to BetterLyrics ratelimit[/magenta]"
                ):
                    await asyncio.sleep(self.ratelimit_time)

    @override
    def observe(self, response_headers: Headers):
        ratelimit_time = cast(str, response_headers.get("Retry-After"))
        if ratelimit_time:
            self.ratelimit_time = int(ratelimit_time)
