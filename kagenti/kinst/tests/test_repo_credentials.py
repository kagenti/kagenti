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

from kagenti.kinst.cli import resolve_repo_credentials


def test_resolve_repo_credentials_literals():
    spec = {"username": "alice", "password": "s3cret"}
    vals = {}
    creds = resolve_repo_credentials(spec, vals)
    assert creds["username"] == "alice"
    assert creds["password"] == "s3cret"


def test_resolve_repo_credentials_from_values():
    spec = {
        "usernamePath": "registries.ghcr.username",
        "passwordPath": "registries.ghcr.password",
    }
    vals = {"registries": {"ghcr": {"username": "ci-user", "password": "ci-pass"}}}
    creds = resolve_repo_credentials(spec, vals)
    assert creds["username"] == "ci-user"
    assert creds["password"] == "ci-pass"


def test_resolve_repo_credentials_none():
    assert resolve_repo_credentials(None, {}) is None
