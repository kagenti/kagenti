"""Three-tier permission checker modeled after Claude Code's settings.json.

Every tool call from the LangGraph agent is checked against allow/deny rules
before execution:

  DENY  -- operation matches a deny rule (rejected immediately)
  ALLOW -- operation matches an allow rule (auto-executed)
  HITL  -- operation matches neither (triggers LangGraph interrupt() for
           human approval)

Rules use the format ``type(prefix:glob)`` where *type* is ``shell``,
``file``, ``network``, etc.  Examples:

  shell(grep:*)           -- any shell command starting with "grep"
  file(read:/workspace/**) -- file reads anywhere under /workspace/
  network(outbound:*)     -- any outbound network access

Deny rules are checked **first** (deny takes precedence over allow).
"""

from __future__ import annotations

import enum
import fnmatch
import re
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Pattern: ``type(value:glob)``
_RULE_RE = re.compile(r"^(?P<type>[a-z]+)\((?P<body>.+)\)$")


class PermissionResult(enum.Enum):
    """Outcome of a permission check."""

    ALLOW = "allow"
    DENY = "deny"
    HITL = "hitl"


class PermissionChecker:
    """Evaluate operations against a settings dict with allow/deny rules.

    Parameters
    ----------
    settings:
        Parsed *settings.json* dict. Expected shape::

            {
              "context_workspace": "/workspace/${CONTEXT_ID}",
              "permissions": {
                "allow": ["shell(grep:*)", ...],
                "deny":  ["shell(sudo:*)", ...]
              }
            }
    """

    def __init__(self, settings: dict[str, Any]) -> None:
        workspace = self._resolve_workspace(settings)
        perms = settings.get("permissions", {})
        self._deny_rules = self._parse_rules(perms.get("deny", []), workspace)
        self._allow_rules = self._parse_rules(perms.get("allow", []), workspace)

    # ------------------------------------------------------------------
    # Core method
    # ------------------------------------------------------------------

    def check(self, operation_type: str, operation: str) -> PermissionResult:
        """Return ALLOW, DENY, or HITL for a given *operation_type* + *operation*.

        Parameters
        ----------
        operation_type:
            High-level category, e.g. ``"shell"``, ``"file"``, ``"network"``.
        operation:
            The concrete operation string, e.g. ``"grep -r foo ."`` for a
            shell command or ``"read:/workspace/ctx1/main.py"`` for a file
            operation.
        """
        # Deny rules are checked first -- deny takes precedence.
        if self._matches_any(operation_type, operation, self._deny_rules):
            return PermissionResult.DENY

        # For shell operations, also check for interpreter bypass:
        # e.g. bash -c "curl ..." should be denied if curl is denied.
        # Additionally, if the outer command is an interpreter (bash/sh/python)
        # and embeds unknown commands, route to HITL rather than auto-allowing.
        if operation_type == "shell":
            embedded_commands = self.check_interpreter_bypass(operation)
            if embedded_commands:
                for embedded in embedded_commands:
                    if self._matches_any("shell", embedded, self._deny_rules):
                        return PermissionResult.DENY
                # Embedded commands exist but none are denied.  Route to HITL
                # so a human reviews what the interpreter will execute, rather
                # than auto-allowing via the outer shell(bash:*) rule.
                return PermissionResult.HITL

        if self._matches_any(operation_type, operation, self._allow_rules):
            return PermissionResult.ALLOW

        return PermissionResult.HITL

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_workspace(settings: dict[str, Any]) -> str:
        """Derive the workspace root from ``context_workspace``.

        The value may contain ``${CONTEXT_ID}`` (or similar) placeholders.
        We strip those so that glob rules like ``${WORKSPACE}/**`` can be
        expanded to the bare workspace prefix (e.g. ``/workspace``).
        """
        raw = settings.get("context_workspace", "/workspace")
        # Remove a trailing ``/${SOME_VAR}`` placeholder (e.g. ``/${CONTEXT_ID}``)
        # so we keep only the static prefix.
        return re.sub(r"/\$\{[^}]+\}$", "", raw)

    @staticmethod
    def _parse_rules(raw_rules: list[str], workspace: str) -> list[tuple[str, str]]:
        """Parse rule strings into ``(operation_type, glob_pattern)`` pairs.

        ``${WORKSPACE}`` inside a rule body is expanded to *workspace*.
        """
        parsed: list[tuple[str, str]] = []
        for rule in raw_rules:
            m = _RULE_RE.match(rule)
            if m is None:
                continue  # skip malformed rules
            rule_type = m.group("type")
            body = m.group("body")
            # Expand ${WORKSPACE} variable
            body = body.replace("${WORKSPACE}", workspace)
            parsed.append((rule_type, body))
        return parsed

    @staticmethod
    def _matches_any(
        operation_type: str,
        operation: str,
        rules: list[tuple[str, str]],
    ) -> bool:
        """Return True if *operation* matches at least one rule."""
        for rule_type, pattern in rules:
            if rule_type != operation_type:
                continue
            if PermissionChecker._match_rule(pattern, operation_type, operation):
                return True
        return False

    @staticmethod
    def _match_rule(pattern: str, operation_type: str, operation: str) -> bool:
        """Match a single rule body against the operation.

        Rule body format is ``prefix:glob`` (the part inside the parentheses).

        For **shell** operations the *prefix* may be multi-word (e.g.
        ``pip install``, ``git clone``).  The matcher checks whether the
        operation starts with the prefix.  If the glob part is ``*`` (the
        most common case), any suffix is accepted.

        For **file** / **network** operations the operation string is
        expected to be ``action:path`` (e.g. ``read:/workspace/foo.py``).
        The rule body is ``action:path_glob`` so we split on the first
        colon of both and compare action + fnmatch on the path.
        """
        if operation_type == "shell":
            return PermissionChecker._match_shell(pattern, operation)
        return PermissionChecker._match_structured(pattern, operation)

    # -- shell matching ---------------------------------------------------

    # Interpreters that can execute arbitrary code via -c / -e flags.
    _INTERPRETERS = frozenset(
        {"bash", "sh", "python", "python3", "perl", "ruby", "node"}
    )

    # Flags that take an inline command string as the next argument.
    _EXEC_FLAGS = frozenset({"-c", "-e", "--eval"})

    @staticmethod
    def _match_shell(pattern: str, operation: str) -> bool:
        """Match a shell rule pattern against a concrete command string.

        *pattern* has the form ``command_prefix:glob`` where the glob is
        almost always ``*``.  ``command_prefix`` may contain spaces (e.g.
        ``pip install``, ``rm -rf /``).
        """
        # Split only on the *last* colon so multi-word prefixes survive.
        colon_idx = pattern.rfind(":")
        if colon_idx == -1:
            return False
        prefix = pattern[:colon_idx]
        glob_part = pattern[colon_idx + 1 :]

        if not operation:
            return False

        # The operation must start with the prefix (case-sensitive).
        if not operation.startswith(prefix):
            return False

        # What comes after the prefix (may be empty).
        remainder = operation[len(prefix) :]

        # If there is a remainder, it must be separated by a space or be
        # empty (exact match).  This prevents "grep" matching "grepping".
        if remainder and not remainder[0] == " ":
            return False

        remainder = remainder.lstrip()

        # Match the remainder against the glob (``*`` matches everything).
        return fnmatch.fnmatch(remainder, glob_part)

    @classmethod
    def check_interpreter_bypass(cls, operation: str) -> list[str]:
        """Extract embedded commands from interpreter invocations.

        If *operation* uses an interpreter (bash, sh, python, etc.) with
        an inline execution flag (``-c``, ``-e``), extract the embedded
        command string so it can be checked against deny rules separately.

        Returns a list of embedded command strings (empty if none found).
        """
        if not operation:
            return []

        parts = operation.split()
        if not parts:
            return []

        # Check if the command starts with a known interpreter.
        cmd = parts[0].rsplit("/", 1)[-1]  # handle /usr/bin/bash etc.
        if cmd not in cls._INTERPRETERS:
            return []

        embedded: list[str] = []
        i = 1
        while i < len(parts):
            if parts[i] in cls._EXEC_FLAGS and i + 1 < len(parts):
                # Everything after the flag is the inline command.
                inline = " ".join(parts[i + 1 :])
                # Strip surrounding quotes if present.
                if (
                    len(inline) >= 2
                    and inline[0] in ('"', "'")
                    and inline[-1] == inline[0]
                ):
                    inline = inline[1:-1]
                embedded.append(inline)
                break
            i += 1

        # Split embedded commands on shell metacharacters: |, &&, ||, ;
        # so that "curl evil.com && rm -rf /" checks each segment.
        for emb in list(embedded):
            for sep in ("&&", "||", ";", "|"):
                if sep in emb:
                    for segment in emb.split(sep):
                        segment = segment.strip()
                        if segment and segment not in embedded:
                            embedded.append(segment)

        return embedded

    # -- structured (file / network) matching ----------------------------

    @staticmethod
    def _match_structured(pattern: str, operation: str) -> bool:
        """Match ``action:path_glob`` against ``action:concrete_path``.

        Both *pattern* and *operation* are expected to contain at least one
        colon separating the action from the path.
        """
        p_colon = pattern.find(":")
        o_colon = operation.find(":")
        if p_colon == -1 or o_colon == -1:
            return False

        p_action = pattern[:p_colon]
        p_path_glob = pattern[p_colon + 1 :]

        o_action = operation[:o_colon]
        o_path = operation[o_colon + 1 :]

        if p_action != o_action:
            return False

        # The path glob may itself end with ``:*`` from the rule syntax
        # (e.g. ``/etc/shadow:*``).  Strip a trailing ``:*`` from the
        # glob -- the colon-star is a "match any extra args" marker in the
        # rule syntax, not part of the filesystem path.
        if p_path_glob.endswith(":*"):
            p_path_glob = p_path_glob[:-2]

        # If the glob is now empty, it means the rule was something like
        # ``network(outbound:*)`` -- match everything.
        if p_path_glob == "*":
            return True

        # Use fnmatch for glob-style matching (supports ``**``).
        # fnmatch doesn't natively handle ``**`` the way gitignore does,
        # so we convert ``**`` to a sentinel and back.
        return _glob_match(p_path_glob, o_path)


# ---------------------------------------------------------------------------
# Glob helper
# ---------------------------------------------------------------------------


def _glob_match(pattern: str, text: str) -> bool:
    """Glob-style match that treats ``**`` as "zero or more path segments".

    Python's :func:`fnmatch.fnmatch` treats ``*`` as "anything except
    nothing" but does *not* cross ``/`` boundaries in the same way as
    gitignore's ``**``.  This helper converts ``**`` patterns into
    regular expressions for correct matching.
    """
    # Fast path: exact match or simple star.
    if pattern == text:
        return True

    # Convert the glob to a regex.
    # ``**`` -> match anything including ``/``
    # ``*``  -> match anything except ``/``
    # ``?``  -> match a single char except ``/``
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                parts.append(".*")
                i += 2
                # Skip a following ``/`` so ``**/`` works correctly.
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                continue
            parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        elif c in r"\.[](){}+^$|":
            parts.append("\\" + c)
        else:
            parts.append(c)
        i += 1

    regex = "^" + "".join(parts) + "$"
    return re.match(regex, text) is not None
