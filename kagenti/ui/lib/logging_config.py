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

"""Centralized logging configuration for the Kagenti UI.

This module provides an idempotent `setup_logging` function that configures the
root logger, ensures there's a single StreamHandler, and optionally registers a
Streamlit-friendly handler that appends logs into an in-memory buffer or a
provided callback. It reads the `KAGENTI_UI_DEBUG` env var when no explicit
level is provided.

Keep this module lightweight and safe to call multiple times (Streamlit will
re-run the script on UI interactions).
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Callable

KAGENTI_UI_DEBUG_ENV = "KAGENTI_UI_DEBUG"
_SETUP_DONE_FLAG = "_kagenti_ui_logging_setup_done"


class StreamlitLogHandler(logging.Handler):
    """A logging handler that forwards formatted log lines to an append callback.

    The callback is expected to be a callable that accepts a single string.
    """

    def __init__(self, append_callback: Callable[[str], None]):
        super().__init__()
        self.append_callback = append_callback
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        try:
            msg = self.format(record)
            self.append_callback(msg)
        except Exception:
            self.handleError(record)


def setup_logging(
    level: Optional[int] = None,
    enable_streamlit_handler: bool = False,
    streamlit_append_callback: Optional[Callable[[str], None]] = None,
):
    """Idempotent logging setup used by the UI.

    - If `level` is None, the function reads the `KAGENTI_UI_DEBUG` env var.
    - Ensures a single `StreamHandler` exists and updates its level.
    - Optionally registers a single `StreamlitLogHandler` using the provided
      append callback.
    """
    root = logging.getLogger()

    # Determine level
    if level is None:
        env_val = os.getenv(KAGENTI_UI_DEBUG_ENV, "").lower()
        if env_val in ("1", "true", "yes"):
            level = logging.DEBUG
        else:
            level = logging.INFO

    # Set root logger level
    root.setLevel(level)

    # Ensure a single StreamHandler exists and set its level
    stream_handler = None
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, StreamlitLogHandler
        ):
            stream_handler = h
            break

    if stream_handler:
        stream_handler.setLevel(level)
    else:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root.addHandler(sh)

    # Optionally add/update the StreamlitLogHandler
    if enable_streamlit_handler and streamlit_append_callback:
        existing = None
        for h in list(root.handlers):
            if isinstance(h, StreamlitLogHandler):
                existing = h
                break
        if existing:
            existing.append_callback = streamlit_append_callback
            existing.setLevel(level)
        else:
            root.addHandler(StreamlitLogHandler(streamlit_append_callback))

    # mark as setup so repeated calls don't add extra handlers beyond the checks above
    setattr(root, _SETUP_DONE_FLAG, True)

    # Also adjust our package logger to the same level for convenience
    logging.getLogger("kagenti.ui").setLevel(level)


def streamlit_debug_checkbox(label: str = "Enable UI debug logs") -> bool:
    """Utility to render a checkbox in Streamlit that toggles debug logging.

    This helper imports Streamlit lazily so `logging_config` can be used in
    non-UI test contexts without requiring Streamlit at import time.
    """
    try:
        # Lazy import: streamlit is optional in non-UI contexts.
        # pylint: disable=import-outside-toplevel
        import streamlit as st
    except Exception as exc:  # pragma: no cover - only runs when Streamlit present
        raise RuntimeError(
            "streamlit is required for streamlit_debug_checkbox"
        ) from exc

    default = os.getenv(KAGENTI_UI_DEBUG_ENV, "").lower() in ("1", "true", "yes")
    if "ui_debug" not in st.session_state:
        st.session_state.ui_debug = default

    val = st.checkbox(label, value=st.session_state.ui_debug)
    if val != st.session_state.ui_debug:
        st.session_state.ui_debug = val
        lvl = logging.DEBUG if val else logging.INFO

        # simple append callback into session state
        def _append(msg: str):
            logs = st.session_state.setdefault("ui_logs", [])
            logs.append(msg)

        setup_logging(
            level=lvl, enable_streamlit_handler=True, streamlit_append_callback=_append
        )
        # trigger a rerun so changes are applied across the app, if available.
        # Use getattr to avoid no-member issues and call inside try/except to
        # tolerate non-callable or missing attributes in test contexts.
        try:
            getattr(st, "experimental_rerun", lambda: None)()  # pylint: disable=not-callable
        except Exception:
            # if rerun fails for tests or other contexts, ignore
            pass

    return st.session_state.ui_debug
