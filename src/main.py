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

# pyright: reportUnknownMemberType=false,reportUnknownVariableType=false
# pyright: reportUnusedCallResult=false,reportUnusedParameter=false

import argparse
import asyncio
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from httpx import AsyncClient, Headers
from mutagen import File
from mutagen.flac import FLAC
from mutagen.id3 import USLT
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

SUPPORTED_EXTENSIONS: set[str] = {".mp3", ".flac", ".opus", ".m4a"}

root_parser = argparse.ArgumentParser(
    prog="lsync",
    usage=f"{sys.argv[0]} sync <directory to traverse 1> [dir to traverse 2]",
    description="Automatically fetches lyrics for your audio files.",
)

subparsers = root_parser.add_subparsers()
sync_parser = subparsers.add_parser("sync")

sync_parser.add_argument("sync", nargs="+")

console = Console()

lyrics_client = AsyncClient(timeout=120)
itunes_client = AsyncClient(timeout=15)


@dataclass
class Ok:
    ok: Literal[True]
    lyrics: str


@dataclass
class Error:
    ok: Literal[False]
    err_msg: str


Result = Ok | Error


@dataclass
class RateLimitState:
    limit: int | None
    remaining: int | None
    limit_type: str | None


class ItunesRateLimiter:
    def __init__(self, max_calls: int, period: int):
        self.max_calls: Final[int] = max_calls
        self.period: Final[int] = period
        self.calls: list[float] = []
        self.lock: Final[asyncio.Lock] = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                console.print(
                    f"[magenta]Sleeping for {sleep_time} s to avoid ratelimit from itunes API[/magenta]"
                )
                await asyncio.sleep(sleep_time)
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())


class BetterLyricsRateLimiter:
    def __init__(self, backoff: float = 2.0):
        self.remaining: int | None = None
        self.backoff: Final[float] = backoff
        self.lock: Final[asyncio.Lock] = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            if self.remaining == 0:
                console.print(
                    f"[magenta] Sleeping for {self.backoff} s due to BetterLyrics ratelimit[/magenta]"
                )
                await asyncio.sleep(self.backoff)

    def update(self, headers: Headers):
        remaining = cast(str, headers.get("X-RateLimit-Remaining"))
        limit_type = cast(str, headers.get("X-RateLimit-Type"))
        if remaining is not None and limit_type == "normal":
            self.remaining = int(remaining)


itunes_limiter = ItunesRateLimiter(max_calls=20, period=60)
betterlyrics_limiter = BetterLyricsRateLimiter()


def write_lyrics(file: Path, lyrics: str) -> bool:
    try:
        au = File(file)
        if not au:
            console.print(
                f"[red]Cannot write lyrics for '{file.name}', mutagen unable to infer type[/red]"
            )
        match au:
            case MP3():
                au.tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))  # pyright: ignore[reportOptionalMemberAccess]
            case FLAC():
                au["LYRICS"] = lyrics
            case OggOpus():
                au["LYRICS"] = lyrics
            case MP4():
                au["©lyr"] = lyrics
            case _:
                console.print(
                    f"[red]Cannot write lyrics for '{file.name}, extension is unsupported'[/red]"
                )
                return False
        au.save()
        return True
    except Exception as e:  # ruff: ignore[blind-except]
        console.print(f"[brred]error adding lyrics to '{file.name}'[/brred]: {e}")
        return False


def read_tags(path: Path) -> tuple[str, str, str, float]:
    audio = File(path, easy=True)
    if not audio:
        console.print(f"[red]Failed to read metadata tags for {path.name}[/red]")
        return "", "", "", 0
    audio = cast(dict[str, str], cast(object, audio))
    artists = audio.get("artist", [""])[0]
    title = audio.get("title", [""])[0]
    album = audio.get("album", [""])[0]
    return title, album, artists, audio.info.length  # pyright: ignore[reportAttributeAccessIssue]


def find_audio_files(dir: Path) -> Generator[Path]:
    for f in dir.rglob("*"):
        if f.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield f


async def _fetch_lyrics_apple(title: str, artist: str) -> Result:
    await itunes_limiter.acquire()
    itunes_response = await itunes_client.get(
        "https://itunes.apple.com/search",
        params={
            "term": f"{title} - {artist}",
            "country": "US",
            "media": "music",
        },
    )

    if itunes_response.status_code != 200:
        return Error(
            False, f"iTunes search failed, status code {itunes_response.status_code}"
        )

    response = cast(dict[str, str], itunes_response.json())
    results = cast(list[dict[str, str]], cast(object, response["results"]))
    if len(results) == 0:
        return Error(False, "iTunes search failed, no match found")
    track_id = results[0]["trackId"]

    lyrics_response = await lyrics_client.get(
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
            False,
            f"Paxsenix lyrics fetch failed, status code {lyrics_response.status_code}, error: {error}",
        )

    return Ok(True, cast(str, lyrics_response.json()["content"]))


async def _fetch_lyrics_betterlyrics(
    title: str, album: str, artist: str, length: float, retry: int = 2
) -> Result:
    params = {
        "s": title,
        "a": artist.replace(" & ", ", "),
        "d": int(length),
    }
    if album:
        params.update({"al": album})
    for attempt in range(retry):
        await betterlyrics_limiter.acquire()
        response = await lyrics_client.get(
            "https://lyrics-api.boidu.dev/getLyrics",
            params=params,
        )
        betterlyrics_limiter.update(response.headers)

        if response.status_code == 200:
            r = cast(dict[str, str], response.json())
            ttml = r["ttml"]
            console.print(
                f"[brcyan]BetterLyrics match found for '{title} - {artist}'[/brcyan]"
            )
            return Ok(True, ttml)
        if response.status_code == 422:
            return Error(
                False,
                f"BetterLyrics match not available for '{title} - {artist}', not enough song data from file metadata",
            )
        if response.status_code == 429 or response.status_code == 401:
            error = (
                f"[yellow]Attempt {attempt + 1}/{retry} failed for '{title} - {artist}'"
            )
            if (attempt + 1) < retry:
                error = f"{error}, retrying[/yellow]"
            else:
                error = f"{error}[/yellow]"
            console.print(error)
            continue
    return Error(False, "No match from BetterLyrics")


async def fetch_lyrics(title: str, album: str, artist: str, length: float) -> Result:
    # return await _fetch_lyrics_apple(title, artist)
    bl_result = await _fetch_lyrics_betterlyrics(title, album, artist, length)
    match bl_result:
        case Ok():
            return bl_result
        case Error():
            console.print(
                f"[yellow]Retrying '{title} - {artist}' with Apple Music instead[/yellow]"
            )
            am_result = await _fetch_lyrics_apple(title, artist)
            match am_result:
                case Ok():
                    return am_result
                case Error():
                    return Error(False, f"All provider tried for '{title} - {artist}'")


async def process_file(path: Path, semaphore: asyncio.Semaphore):
    title, album, artist, length = await asyncio.to_thread(read_tags, path)
    if not title or not artist:
        console.print(f"[yellow]Not enough song metadata for {path.name}[/yellow]")
        return
    async with semaphore:
        lyrics = await fetch_lyrics(title, album, artist, length)
        match lyrics:
            case Error():
                console.print(
                    f"[red]Failed to fetch lyrics for '{title} - {artist}': {lyrics.err_msg}[/red]"
                )
                return
            case Ok():
                ret = await asyncio.to_thread(write_lyrics, path, lyrics.lyrics)
                if ret:
                    console.print(f"[green]Wrote lyrics for '{path.name}'[/green]")
                else:
                    console.print(
                        f"[red]Failed to write lyrics for '{path.name}'[/red]"
                    )


async def main():
    parsed = root_parser.parse_args()
    if hasattr(parsed, "sync"):
        valid_files: list[Path] = []
        semaphore = asyncio.Semaphore(3)
        for d in cast(list[str], parsed.sync):
            valid_files.extend(list(find_audio_files(Path(d))))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as p:
            task_id = p.add_task("Fetching lyrics", total=len(valid_files))

            async def process_and_advance(path: Path):
                await process_file(path, semaphore)
                p.advance(task_id)

            await asyncio.gather(*(process_and_advance(path) for path in valid_files))
            await lyrics_client.aclose()
            await itunes_client.aclose()
    else:
        root_parser.print_help()
