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

from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text


class LiveInfo:  # I can't think of a better name
    def __init__(self, c: Console) -> None:
        self.console: Final[Console] = c

        self.synced: int = 0
        self.fallback: int = 0
        self.skipped: int = 0
        self.failures: list[str] = []
        self.retries: list[str] = []
        self.status: str = ""

        self._progress = Progress(
            SpinnerColumn(),
            MofNCompleteColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        self._task = self._progress.add_task("Fetching lyrics", total=0)
        self._live = Live(
            get_renderable=self._render, console=self.console, refresh_per_second=15
        )

    @contextmanager
    def waiting(self, msg: str) -> Generator[None]:
        self.status = msg
        try:
            yield
        finally:
            self.status = ""

    def _render(self) -> Group:
        t_retries = Table.grid()
        p_retries = Panel(t_retries, border_style="bold yellow")
        render_retries = False
        if self.retries:
            render_retries = True
            for r in self.retries[-3:]:
                t_retries.add_row(r)

        t_summary = Table.grid(padding=(0, 2))
        p_summary = Panel(t_summary, border_style="bold cyan")
        t_summary.add_row("[bold][green]Synced[/]", f"[green]{self.synced}[/]")
        if self.fallback:
            t_summary.add_row(
                "[grey50]  via fallback[/]", f"[grey50]{self.fallback}[/]"
            )
        if self.skipped:
            t_summary.add_row("[grey50]Skipped[/]", f"[grey50]{self.skipped}[/]")
        if self.failures:
            t_summary.add_row("[bold][red]Failures[/]", f"[red]{len(self.failures)}[/]")
        if self.status:
            t_summary.add_row("[bold][magenta]waiting[/]", f"[magenta]{self.status}[/]")

        if render_retries:
            return Group(p_retries, p_summary, self._progress)
        return Group(p_summary, self._progress)

    def start(self) -> None:
        self._live.start(refresh=True)

    def stop(self) -> None:
        self._progress.stop()
        # Text() is mostly a precaution, a valid rich markup in a song/artist
        # title will screw this up without Text() (though I doubt we'd ever
        # encounter one tbh)
        self.console.print(Text("\n".join(self.failures), style="red"))
        self.retries.clear()
        self._live.refresh()
        self._live.stop()

    def update_total(self, total: int) -> None:
        self._progress.update(self._task, total=total)

    def increment_prog_bar(self, increment_by: int = 1) -> None:
        self._progress.advance(self._task, increment_by)
