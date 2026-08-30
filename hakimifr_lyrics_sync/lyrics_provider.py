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
from typing import Any, ClassVar, Final, cast, final, override

from httpx import AsyncClient

from hakimifr_lyrics_sync import console, live_info
from hakimifr_lyrics_sync.rate_limiter import (
    BetterLyricsRateLimiter,
    ItunesRateLimiter,
    LrcLibRateLimiter,
    RateLimiter,
)
from hakimifr_lyrics_sync.types import Error, Lyrics, Ok, Result, SyncLevel, Track


class LyricsProvider(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    type: ClassVar[SyncLevel]
    client: AsyncClient
    rate_limiter: RateLimiter

    @abstractmethod
    async def fetch(self, track: Track) -> Result: ...

    def supports(self, track: Track) -> bool:
        return True

    @abstractmethod
    async def close(self) -> None: ...


@final
class AppleMusic(LyricsProvider):
    id = "apple-music"
    name = "Apple Music + iTunes (TTML)"
    type = "ttml"

    def __init__(self, apple_dev_token: str, apple_media_user_token: str) -> None:
        self.client: AsyncClient = AsyncClient(timeout=120)
        self.rate_limiter = ItunesRateLimiter(20, 60)
        self.apple_dev_token: Final[str] = apple_dev_token
        self.apple_media_user_token: Final[str] = apple_media_user_token

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
            return Error(f"iTunes search failed, status code {itunes_response.status_code}")

        response = cast(dict[str, str], itunes_response.json())
        results = cast(list[dict[str, str]], cast(object, response["results"]))

        if len(results) == 0:
            return Error("iTunes search failed, no match found")
        track_id = results[0]["trackId"]

        lyrics_response = await self.client.get(
            f"https://amp-api.music.apple.com/v1/catalog/my/songs/{track_id}/syllable-lyrics?l%5Blyrics%5D=en-gb&l%5Bscript%5D=en-Latn&extend=ttmlLocalizations",
            headers={
                "Authorization": f"Bearer {self.apple_dev_token}",
                "Origin": "https://music.apple.com",
                "Referer": "https://music.apple.com/",
                "Media-User-Token": self.apple_media_user_token,
                "Accept-Language": "en-MY,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            timeout=30,
        )

        if lyrics_response.status_code != 200:
            return Error("iTunes search succeeded but fetching lyrics from Apple Music failed")

        response = cast(dict[str, Any], lyrics_response.json())  # pyright: ignore[reportExplicitAny]
        ttml_attributes = response["data"][0].get("attributes")  # pyright: ignore[reportAny]
        ttml = ttml_attributes.get("ttmlLocalizations") or ttml_attributes.get("ttml")  # pyright: ignore[reportAny]

        if not ttml:
            return Error("unexpected missing of lyrics from Apple because status code was 200")

        return Ok(
            Lyrics(
                content=ttml,  # pyright: ignore[reportAny]
                format="ttml",
                provider=self.name,
            )
        )

    @override
    async def close(self) -> None:
        await self.client.aclose()


@final
class Paxsenix(LyricsProvider):
    id = "paxsenix"
    name = "Paxsenix + iTunes (TTML)"
    type = "ttml"

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
            return Error(f"iTunes search failed, status code {itunes_response.status_code}")

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

        return Ok(
            Lyrics(
                content=cast(str, lyrics_response.json()["content"]),
                format=self.type,
                provider=self.name,
            )
        )

    @override
    def supports(self, track: Track) -> bool:
        return not (not track.title or not track.artist)

    @override
    async def close(self):
        await self.client.aclose()


@final
class BetterLyrics(LyricsProvider):
    id = "better-lyrics"
    name = "Better Lyrics (TTML)"
    type = "ttml"

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
        for _attempt in range(retry):
            await self.rate_limiter.acquire()
            response = await self.client.get(
                "https://lyrics-api.boidu.dev/getLyrics",
                params=params,
            )
            self.rate_limiter.observe(response.headers)

            if response.status_code == 200:
                r = cast(dict[str, str], response.json())
                ttml = r["ttml"]
                return Ok(
                    Lyrics(
                        content=ttml,
                        provider=self.name,
                        format=self.type,
                    )
                )
            if response.status_code == 422:
                return Error(
                    f"BetterLyrics match not available for '{track.title} - {track.artist}', not enough song data from file metadata"
                )
            if response.status_code == 429 or response.status_code == 401:
                continue
        return Error("No match from BetterLyrics")

    @override
    def supports(self, track: Track) -> bool:
        return not (not track.title or not track.artist or not track.length)

    @override
    async def close(self) -> None:
        await self.client.aclose()


@final
class LrcLib(LyricsProvider):
    id = "lrclib"
    name = "LRCLIB (LRC)"
    type = "lrc"

    def __init__(self):
        self.client: AsyncClient = AsyncClient(
            headers={"User-Agent": "LRCGET v0.2.0 (https://github.com/hakimifr/lyrics-sync)"}
        )
        self.rate_limiter = LrcLibRateLimiter()

    @override
    async def fetch(self, track: Track, retry: int = 2) -> Result:
        await self.rate_limiter.acquire()
        params = {
            "track_name": track.title,
            "artist_name": track.artist,
            "duration": track.length,
        }
        if track.album:
            params.update({"album_name": track.album})
        attempt = 0
        while attempt < retry:
            response = await self.client.get("https://lrclib.net/api/get", params=params)
            self.rate_limiter.observe(response.headers)

            r = cast(dict[str, str], response.json())
            if response.status_code == 200:
                lrc: str = r.get("syncedLyrics", "") or r.get("plainLyrics", "")
                if not lrc:
                    return Error("LRCLIB return status code 200, but malformed lyrics output")
                return Ok(
                    Lyrics(
                        content=lrc,
                        format=self.type,
                        provider=self.name,
                    )
                )
            if response.status_code == 404:
                if params.get("album_name") is not None:
                    params.pop("album_name")
                    live_info.retries.append(
                        f"LRCLIB: retrying '{track.title} - {track.artist}' without album name"
                    )
                    continue
                return Error("no match from LRCLIB")
            if response.status_code == 429:
                continue
            attempt += 1
        return Error("unable to fetch from LRCLIB, keep getting ratelimited")

    @override
    async def close(self) -> None:
        await self.client.aclose()


class LyricsFetcher:
    def __init__(self, providers: Sequence[LyricsProvider]):
        self.providers: Final = providers
        console.print(f"[bold]Default provider is {self.providers[0].name}[/bold]")
        console.print(
            f"  All providers, in order of priority: {', '.join(p.name for p in self.providers)}"
        )

    async def fetch(self, track: Track) -> Result:
        fails: list[str] = []
        for p in self.providers:
            if not p.supports(track):
                continue

            match await p.fetch(track):
                case Ok() as ok:
                    live_info.synced += 1
                    console.print(
                        f"Match found for '{track.title} - {track.artist}' with provider '{p.name}'"
                    )
                    if fails:
                        live_info.fallback += 1
                    return ok
                case Error() as err:
                    next_provider = self.providers.index(p) + 1
                    if next_provider < len(self.providers):
                        live_info.retries.append(
                            f"Retrying '{track.title} - {track.artist}' with provider {self.providers[next_provider].name}"
                        )
                    fails.append(f"{p.name}: {err.err_msg}")

        return Error("; ".join(fails) or "track unsupported by all providers")

    async def close(self) -> None:
        for p in self.providers:
            await p.close()
