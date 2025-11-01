# Assisted by watsonx Code Assistant
# Copyright 2025 IBM Corp.
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

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import List, Optional

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.spinner import Spinner

console = Console()


class Status(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    desc: str
    status: Status = Status.PENDING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[str] = None


class ProgressManager:
    def __init__(self) -> None:
        self.tasks: List[Task] = []
        self._live: Optional[Live] = None

    def add(self, id: str, desc: str) -> Task:
        t = Task(id=id, desc=desc)
        self.tasks.append(t)
        return t

    def _render(self) -> Table:
        tbl = Table.grid(expand=True)
        for t in self.tasks:
            if t.status == Status.PENDING:
                sym = "…"
            elif t.status == Status.RUNNING:
                sym = Spinner("dots", text="")
            elif t.status == Status.SUCCESS:
                sym = "[green]✅[/green]"
            else:
                sym = "[red]❌[/red]"

            elapsed = ""
            if t.started_at:
                end = t.finished_at or monotonic()
                elapsed = f"{end - t.started_at:.1f}s"

            # Pass renderables directly to the Table (don't convert renderables to string).
            # Converting a Spinner to a string produced the object repr like
            # "<rich.spinner.Spinner object at 0x...>". Let rich render the Spinner.
            tbl.add_row(sym, t.desc, elapsed, t.result or "")
        return tbl

    def __enter__(self):
        # Use live rendering only when stdout is a TTY
        if console.is_terminal:
            self._live = Live(self._render(), refresh_per_second=10, console=console)
            self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._live:
            self._live.update(self._render())
            self._live.__exit__(exc_type, exc, tb)


class Step:
    def __init__(self, manager: ProgressManager, task: Task) -> None:
        self.manager = manager
        self.task = task

    def __enter__(self):
        self.task.status = Status.RUNNING
        self.task.started_at = monotonic()
        if self.manager._live:
            self.manager._live.update(self.manager._render())
        else:
            console.print(f"[RUNNING] {self.task.desc}")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.task.finished_at = monotonic()
        if exc_type is None:
            self.task.status = Status.SUCCESS
            self.task.result = "ok"
        else:
            self.task.status = Status.FAILED
            # short result message: include exception type and message so the
            # progress table shows the real error (not just the exception class).
            try:
                msg = str(exc) if exc is not None else ""
            except Exception:
                msg = ""
            if msg:
                self.task.result = f"{exc_type.__name__}: {msg}"
            else:
                self.task.result = str(exc_type.__name__)

        if self.manager._live:
            self.manager._live.update(self.manager._render())
        else:
            status = "OK" if self.task.status == Status.SUCCESS else "FAILED"
            console.print(f"[{status}] {self.task.desc} {self.task.result}")

        # do not swallow exceptions
        return False
