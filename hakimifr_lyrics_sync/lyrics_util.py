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

import re
from xml.etree import ElementTree

from hakimifr_lyrics_sync.types import SyncLevel

_XML_PROLOG = re.compile(r"^\s*(?:<\?xml|<!--|<tt\b|<[a-zA-Z_])")
_LRC_LINE = re.compile(r"^[ \t]*\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]", re.MULTILINE)
_ELRC_WORD = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")


def detect_format(text: str) -> SyncLevel:
    if _XML_PROLOG.match(text):
        try:
            ElementTree.fromstring(text)
            return "ttml"
        except ElementTree.ParseError:
            pass

    if _LRC_LINE.search(text):
        return "elrc" if _ELRC_WORD.search(text) else "lrc"

    return "plain"
