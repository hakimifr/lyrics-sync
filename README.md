# lyrics-sync

A python package to sync your local songs' lyrics, mainly TTML. Therefore, you
need a player that can parse TTML and show syllable-synced lyrics. I recommend
[Gramophone](https://github.com/FoedusProgramme/Gramophone/).

To use, simply run this in Termux (you need uv installed, `pkg install uv`):

```sh
uvx --from hakimifr-lyrics-sync@latest lsync <path-to-music-files 1> [path-to-music-files 2] ...
```

where `path-to-music-files` is a directory or files. Directories will be
traversed recursively.

It's fine to run the script many times on the same directory, as the script
maintains its own JSON containing list of files that have already been synced.
Any failed sync will be reattempted when ran on the same directory.

## Lyrics Source

Currently, lyrics are, in order of priority, sourced from BetterLyrics (TTML),
Paxsenix (TTML) and LRCLIB (LRC). Granted, BetterLyrics mostly source their
TTML from Apple, and so Paxsenix might seem redundant. But BetterLyrics
endpoint sometimes does not have a match, especially if the audio files
metadata differs even slightly. In which case, Paxsenix might actually succeds.

The reason is, Paxsenix is not alone on its own because the API only allows
fetching Apple's TTML by the Apple Music/iTunes song id. So, Paxsenix
implementation actually uses iTunes search API to get the song id, and only
then is it fetched from Paxsenix's cache. Please see
[`lyrics_provider.py`](./hakimifr_lyrics_sync/lyrics_provider.py) to see the
actual implementation. TL;DR, Paxsenix is actually iTunes + Paxsenix itself.

## License

```
Copyright 2026 Firdaus Hakimi <hakimifr@proton.me>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
