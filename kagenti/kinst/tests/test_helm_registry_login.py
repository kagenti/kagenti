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

from types import SimpleNamespace

import pytest

from kagenti.kinst import cli


def test_helm_registry_login_with_literal_creds(monkeypatch):
    calls = []

    def fake_run_cmd(cmd, input_data=None, check=True):
        calls.append(list(cmd))
        # return a minimal object with expected attributes
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "run_cmd", fake_run_cmd)

    # call helm_upgrade_install with an OCI repository and explicit credentials
    repo = "oci://ghcr.io/myorg"
    cli.helm_upgrade_install(
        release="rel",
        name="mychart",
        repository=repo,
        chart_version=None,
        values_file=None,
        namespace=None,
        kube_context=None,
        dry_run=True,
        wait=False,
        timeout=None,
        repo_credentials={"username": "u", "password": "p"},
    )

    # first call should be helm registry login
    assert calls, "no commands were run"
    assert calls[0][0:3] == ["helm", "registry", "login"]
    assert "ghcr.io" in calls[0]
    # second call should be helm upgrade/install
    assert any(
        c[0:3] == ["helm", "upgrade", "--install"] for c in calls
    ), f"upgrade not called, got {calls}"


def test_helm_registry_login_with_token(monkeypatch):
    calls = []

    def fake_run_cmd(cmd, input_data=None, check=True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "run_cmd", fake_run_cmd)

    repo = "oci://ghcr.io/myorg"
    cli.helm_upgrade_install(
        release="rel",
        name="mychart",
        repository=repo,
        chart_version=None,
        values_file=None,
        namespace=None,
        kube_context=None,
        dry_run=True,
        wait=False,
        timeout=None,
        repo_credentials={"token": "tok-abc"},
    )

    assert calls, "no commands were run"
    # login with token should use username '_token'
    login = calls[0]
    assert login[0:3] == ["helm", "registry", "login"]
    assert "_token" in login
