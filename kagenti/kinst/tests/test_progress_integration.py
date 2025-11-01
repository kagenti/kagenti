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


def test_integration_non_tty_multiple_steps(capsys, monkeypatch):
    """Smoke test: run multiple steps under a non-TTY ProgressManager and verify printed output and status."""

    # force non-tty path by swapping the module console with a fake console
    class FakeConsole:
        def __init__(self):
            self.is_terminal = False

        def print(self, *args, **kwargs):
            print(*args, **kwargs)

    monkeypatch.setattr(prog, "console", FakeConsole())

    pm = prog.ProgressManager()
    t1 = pm.add("one", "first step")
    t2 = pm.add("two", "second step")

    with pm:
        with prog.Step(pm, t1):
            pass
        with prog.Step(pm, t2):
            pass

    out = capsys.readouterr().out
    assert "first step" in out
    assert "second step" in out
    assert "OK" in out or "[OK]" in out

    assert t1.status == prog.Status.SUCCESS
    assert t2.status == prog.Status.SUCCESS
