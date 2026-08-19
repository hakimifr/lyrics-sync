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
from rich.table import Table

from hakimifr_lyrics_sync import console
from hakimifr_lyrics_sync.lyrics_provider import Apple, BetterLyrics, LyricsFetcher
from hakimifr_lyrics_sync.store import Config, LastSyncInfo
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

config = Config()
lyrics_fetcher = LyricsFetcher((BetterLyrics(), Apple()))


@dataclass
class RateLimitState:
    limit: int | None
    remaining: int | None
    limit_type: str | None


def write_lyrics(file: Path, lyrics: str) -> bool:
    try:
        audio = File(file)
        if not audio:
            console.print(
                f"[red]Cannot write lyrics for '{file.name}', mutagen unable to infer type[/red]"
            )
        match audio:
            case MP3():
                audio.tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))  # pyright: ignore[reportOptionalMemberAccess]
            case FLAC():
                audio["LYRICS"] = lyrics
            case OggOpus():
                audio["LYRICS"] = lyrics
            case MP4():
                audio["©lyr"] = lyrics
            case _:
                console.print(
                    f"[red]Cannot write lyrics for '{file.name}, extension is unsupported'[/red]"
                )
                return False
        audio.save()
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


async def process_file(path: Path, semaphore: asyncio.Semaphore) -> bool:
    track = await asyncio.to_thread(read_tags, path)
    if config.should_sync(path) in {
        LastSyncInfo.SUCCESSFUL,
        LastSyncInfo.ALREADY_SYNCED,
    }:
        console.print(f"Skipping already synced file '{path.name}'")
        return True
    if not track.title or not track.artist:
        console.print(f"[yellow]Not enough song metadata for {path.name}[/yellow]")
        return False
    async with semaphore:
        lyrics = await lyrics_fetcher.fetch(track)
        match lyrics:
            case Error():
                console.print(
                    f"[red]Failed to fetch lyrics for '{track.title} - {track.artist}': {lyrics.err_msg}[/red]"
                )
                config.store_sync_info(path, LastSyncInfo.FAILED, "ttml")
                return False
            case Ok():
                ret = await asyncio.to_thread(write_lyrics, path, lyrics.lyrics)
                if not ret:
                    console.print(
                        f"[red]Failed to write lyrics for '{path.name}'[/red]"
                    )
                    config.store_sync_info(path, LastSyncInfo.FAILED, "ttml")
                    return False
                config.store_sync_info(path, LastSyncInfo.SUCCESSFUL, "ttml")
                return True


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
                r = await process_file(path, semaphore)
                p.advance(task_id)
                return r

            results_futures = await asyncio.gather(
                *(process_and_advance(path) for path in valid_files)
            )
            results = [f for f in results_futures]
            await lyrics_fetcher.close()
            t = Table("[brgreen]success[/brgreen]", "[brred]failures[/brred]")
            t.add_row(str(results.count(True)), str(results.count(False)))
            config.save_config_to_file()
            console.print(t)
    else:
        root_parser.print_help()
