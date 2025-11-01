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

from kagenti.kinst import progress as prog


def test_step_non_tty_outputs_status(capsys, monkeypatch):
    """When console is non-TTY the Step should print fallback lines and set task status to SUCCESS."""

    # force non-tty path by swapping the module console with a fake console
    class FakeConsole:
        def __init__(self):
            self.is_terminal = False

        def print(self, *args, **kwargs):
            # delegate to built-in print so capsys can capture
            print(*args, **kwargs)

    monkeypatch.setattr(prog, "console", FakeConsole())

    pm = prog.ProgressManager()
    task = pm.add("t1", "do something")

    # use the Step context manager (no exception inside)
    with prog.Step(pm, task):
        # nothing
        pass

    out = capsys.readouterr().out

    # fallback prints should include RUNNING and OK markers and the description
    assert "RUNNING" in out or "[RUNNING]" in out
    assert "OK" in out or "[OK]" in out
    assert "do something" in out

    # task status/result should be set by the context manager
    assert task.status == prog.Status.SUCCESS
    assert task.result == "ok"


def test_render_returns_table():
    """Ensure _render returns a rich Table renderable without error."""
    pm = prog.ProgressManager()
    pm.add("a", "alpha")
    tbl = pm._render()
    # basic sanity checks
    from rich.table import Table

    assert isinstance(tbl, Table)
