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

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Final, cast, get_args

from hakimifr_lyrics_sync.types import SyncLevel


@dataclass
class LyricsRecord:
    sync_level: SyncLevel
    audio_file_path: str
    last_sync_time: float | None


@dataclass
class ConfigRoot:
    lyrics_successful_sync: list[LyricsRecord] = field(default_factory=list)
    lyrics_failed_sync: list[LyricsRecord] = field(default_factory=list)
    lyrics_already_synced: list[LyricsRecord] = field(default_factory=list)


class LastSyncInfo(Enum):
    SUCCESSFUL = auto()
    FAILED = auto()
    ALREADY_SYNCED = auto()
    NEVER_SYNCED = auto()


class Config:
    def __init__(self, config_path: Path | None = None):
        if config_path is None:
            cpath = Path.home().joinpath(".lsync.json")
        else:
            cpath = config_path
        self.config_path: Final[Path] = cpath
        self._config: ConfigRoot | None = None
        self.synced_to_file: bool = True

    def load_from_file(self) -> ConfigRoot:
        if not self.config_path.exists():
            self._config = ConfigRoot()
            self.synced_to_file = True
            return self._config

        with self.config_path.open("r") as f:
            data = json.load(f)  # pyright: ignore[reportAny]

        if not isinstance(data, dict):
            raise TypeError(
                f"config file '{self.config_path.as_posix()}' parsing error"
            )

        def record(d: dict[str, str | float | None]) -> LyricsRecord:
            record = cast(dict[str, object], d)
            sync_level = record.get("sync_level")
            audio_file_path = record.get("audio_file_path")
            last_sync_time = record.get("last_sync_time")

            if not isinstance(audio_file_path, str) or not isinstance(
                last_sync_time, float | None
            ):
                raise TypeError(
                    f"config file '{self.config_path.as_posix()}' is corrupted"
                )

            if sync_level not in get_args(SyncLevel.__value__):  # pyright: ignore[reportAny]
                raise TypeError(f"incorrect sync level for file {d['audio_file_path']}")
            return LyricsRecord(
                sync_level=cast(SyncLevel, sync_level),
                audio_file_path=audio_file_path,
                last_sync_time=last_sync_time,
            )

        config = ConfigRoot(**{
            k: [record(r) for r in v]  # pyright: ignore[reportUnknownArgumentType]
            for k, v in data.items()
        })
        self._config = config
        self.synced_to_file = True
        return config

    def save_config_to_file(self) -> None:
        with self.config_path.open("w") as f:
            json.dump(asdict(self.config), f, indent=2)

    @property
    def config(self) -> ConfigRoot:
        if self._config is None:
            return self.load_from_file()
        return self._config

    @config.setter
    def config(self, config: ConfigRoot) -> None:
        self._config = config
        self.save_config_to_file()

    def should_sync(self, path: Path) -> LastSyncInfo:
        if path.as_posix() in (
            f.audio_file_path for f in self.config.lyrics_successful_sync
        ):
            return LastSyncInfo.SUCCESSFUL
        if path.as_posix() in (
            f.audio_file_path for f in self.config.lyrics_already_synced
        ):
            return LastSyncInfo.ALREADY_SYNCED
        if path.as_posix() in (
            f.audio_file_path for f in self.config.lyrics_failed_sync
        ):
            return LastSyncInfo.FAILED
        return LastSyncInfo.NEVER_SYNCED

    def store_sync_info(
        self, path: Path, sync_info: LastSyncInfo, sync_level: SyncLevel
    ):
        p = path.as_posix()
        match sync_info:
            case LastSyncInfo.SUCCESSFUL:
                if p not in [
                    l.audio_file_path for l in self.config.lyrics_successful_sync
                ]:
                    self.config.lyrics_successful_sync.append(
                        LyricsRecord(sync_level, p, time.time())
                    )
                    self.config.lyrics_failed_sync = [
                        l
                        for l in self.config.lyrics_failed_sync
                        if l.audio_file_path != p
                    ]
            case LastSyncInfo.ALREADY_SYNCED:
                if p not in [
                    l.audio_file_path for l in self.config.lyrics_already_synced
                ]:
                    self.config.lyrics_already_synced.append(
                        LyricsRecord(sync_level, p, time.time())
                    )
                    self.config.lyrics_failed_sync = [
                        l
                        for l in self.config.lyrics_failed_sync
                        if l.audio_file_path != p
                    ]
            case LastSyncInfo.FAILED:
                if p not in [l.audio_file_path for l in self.config.lyrics_failed_sync]:
                    self.config.lyrics_failed_sync.append(
                        LyricsRecord(sync_level, p, time.time())
                    )
            case LastSyncInfo.NEVER_SYNCED:
                raise TypeError("store operation not supported for NEVER_SYNCED")
