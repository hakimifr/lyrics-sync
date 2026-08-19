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

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Final, cast, final, override

from httpx import AsyncClient

from hakimifr_lyrics_sync import console
from hakimifr_lyrics_sync.rate_limiter import (
    BetterLyricsRateLimiter,
    ItunesRateLimiter,
    RateLimiter,
)
from hakimifr_lyrics_sync.types import Error, Ok, Result, Track


class LyricsProvider(ABC):
    name: ClassVar[str]
    client: AsyncClient
    rate_limiter: RateLimiter

    @abstractmethod
    async def fetch(self, track: Track) -> Result: ...

    def supports(self, track: Track) -> bool:
        return True

    @abstractmethod
    async def close(self) -> None: ...


@final
class Apple(LyricsProvider):
    name = "Apple Music"

    def __init__(self):
        self.client: AsyncClient = AsyncClient(timeout=120)
        self.rate_limiter = ItunesRateLimiter(20, 60)

    @override
    async def fetch(self, track: Track) -> Result:
        await self.rate_limiter.acquire()
        itunes_response = await self.client.get(
            "https://itunes.apple.com/search",
            params={
                "term": f"{track.title} - {track.artist}",
                "country": "US",
                "media": "music",
            },
        )

        if itunes_response.status_code != 200:
            return Error(
                f"iTunes search failed, status code {itunes_response.status_code}"
            )

        response = cast(dict[str, str], itunes_response.json())
        results = cast(list[dict[str, str]], cast(object, response["results"]))
        if len(results) == 0:
            return Error("iTunes search failed, no match found")
        track_id = results[0]["trackId"]

        lyrics_response = await self.client.get(
            "https://lyrics.paxsenix.org/apple-music/lyrics",
            params={
                "id": track_id,
                "ttml": True,
                "v": 2,
            },
        )

        if lyrics_response.status_code != 200:
            error = cast(str, lyrics_response.json()["error"]["message"])
            return Error(
                f"Paxsenix lyrics fetch failed, status code {lyrics_response.status_code}, error: {error}"
            )

        console.print(
            f"Apple Music lyrics match found for '{track.title} - {track.artist}'"
        )
        return Ok(cast(str, lyrics_response.json()["content"]))

    @override
    def supports(self, track: Track) -> bool:
        return not (not track.title or not track.artist)

    @override
    async def close(self):
        await self.client.aclose()


@final
class BetterLyrics(LyricsProvider):
    name = "Better Lyrics"

    def __init__(self):
        self.client: AsyncClient = AsyncClient()
        self.rate_limiter = BetterLyricsRateLimiter()

    @override
    async def fetch(self, track: Track, retry: int = 2) -> Result:
        params = {
            "s": track.title,
            "a": track.artist.replace(" & ", ", "),
            "d": int(track.length),
        }
        if track.album:
            params.update({"al": track.album})
        for attempt in range(retry):
            await self.rate_limiter.acquire()
            response = await self.client.get(
                "https://lyrics-api.boidu.dev/getLyrics",
                params=params,
            )
            self.rate_limiter.observe(response.headers)

            if response.status_code == 200:
                r = cast(dict[str, str], response.json())
                ttml = r["ttml"]
                console.print(
                    f"[brcyan]BetterLyrics match found for '{track.title} - {track.artist}'[/brcyan]"
                )
                return Ok(ttml)
            if response.status_code == 422:
                return Error(
                    f"BetterLyrics match not available for '{track.title} - {track.artist}', not enough song data from file metadata"
                )
            if response.status_code == 429 or response.status_code == 401:
                error = f"[yellow]Attempt {attempt + 1}/{retry} failed for '{track.title} - {track.artist}'"
                if (attempt + 1) < retry:
                    error = f"{error}, retrying[/yellow]"
                else:
                    error = f"{error}[/yellow]"
                console.print(error)
                continue
        return Error("No match from BetterLyrics")

    @override
    def supports(self, track: Track) -> bool:
        return not (not track.title or not track.artist or not track.length)

    @override
    async def close(self) -> None:
        await self.client.aclose()


class LyricsFetcher:
    def __init__(self, providers: Sequence[LyricsProvider]):
        self.providers: Final = providers
        console.print(f"[bold]Default provider is {self.providers[0].name}[/bold]")

    async def fetch(self, track: Track) -> Result:
        fails: list[str] = []
        for p in self.providers:
            if not p.supports(track):
                continue

            match await p.fetch(track):
                case Ok() as ok:
                    return ok
                case Error() as err:
                    next_provider = self.providers.index(p) + 1
                    if next_provider < len(self.providers):
                        console.print(
                            f"[yellow]Retrying '{track.title} - {track.artist}' with provider {self.providers[next_provider].name}[/yellow]"
                        )
                    fails.append(f"{p.name}: {err.err_msg}")

        return Error("; ".join(fails) or "track unsupported by all providers")

    async def close(self) -> None:
        for p in self.providers:
            await p.close()
