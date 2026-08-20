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

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type SyncLevel = Literal["ttml", "elrc", "lrc", "plain"]


@dataclass
class Ok:
    lyrics: Lyrics
    ok: Literal[True] = True


@dataclass
class Error:
    err_msg: str
    ok: Literal[False] = False


Result = Ok | Error


@dataclass
class Track:
    title: str
    album: str
    artist: str
    length: float
    path: Path


@dataclass
class Lyrics:
    content: str
    format: SyncLevel
    provider: str
