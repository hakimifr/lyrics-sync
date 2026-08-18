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

import argparse
import asyncio
import sys
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mutagen import File
from mutagen.flac import FLAC
from mutagen.id3 import USLT
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from hakimifr_lyrics_sync import console
from hakimifr_lyrics_sync.provider import Apple, BetterLyrics, LyricsFetcher
from hakimifr_lyrics_sync.types import Error, Ok, Track

SUPPORTED_EXTENSIONS: set[str] = {".mp3", ".flac", ".opus", ".m4a"}

root_parser = argparse.ArgumentParser(
    prog="lsync",
    usage=f"{sys.argv[0]} sync <directory to traverse 1> [dir to traverse 2]",
    description="Automatically fetches lyrics for your audio files.",
)

subparsers = root_parser.add_subparsers()
sync_parser = subparsers.add_parser("sync")

sync_parser.add_argument("sync", nargs="+")

lyrics_fetcher = LyricsFetcher((BetterLyrics(), Apple()))


@dataclass
class RateLimitState:
    limit: int | None
    remaining: int | None
    limit_type: str | None


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


def read_tags(path: Path) -> Track:
    audio = File(path, easy=True)
    if not audio:
        console.print(f"[red]Failed to read metadata tags for {path.name}[/red]")
        return Track("", "", "", 0, path)
    audio = cast(dict[str, str], cast(object, audio))
    artists = audio.get("artist", [""])[0]
    title = audio.get("title", [""])[0]
    album = audio.get("album", [""])[0]
    return Track(
        title=title,
        album=album,
        artist=artists,
        length=cast(float, audio.info.length),  # pyright: ignore[reportAttributeAccessIssue]
        path=path,
    )


def find_audio_files(dir: Path) -> Generator[Path]:
    for f in dir.rglob("*"):
        if f.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield f


async def process_file(path: Path, semaphore: asyncio.Semaphore):
    track = await asyncio.to_thread(read_tags, path)
    if not track.title or not track.artist:
        console.print(f"[yellow]Not enough song metadata for {path.name}[/yellow]")
        return
    async with semaphore:
        lyrics = await lyrics_fetcher.fetch(track)
        match lyrics:
            case Error():
                console.print(
                    f"[red]Failed to fetch lyrics for '{track.title} - {track.artist}': {lyrics.err_msg}[/red]"
                )
                return
            case Ok():
                ret = await asyncio.to_thread(write_lyrics, path, lyrics.lyrics)
                if not ret:
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
            p.update(task_id, completed=True)
            await lyrics_fetcher.close()
    else:
        root_parser.print_help()
