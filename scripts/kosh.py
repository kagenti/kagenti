#!/usr/bin/env -S uv run --with openshell==0.0.59 --with click
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "openshell==0.0.59",
#     "click>=8.0",
# ]
# ///
"""kosh - Kagenti OpenShell CLI wrapper.

Proxies all openshell subcommands (gateway, sandbox, status, etc.) and adds
kagenti-specific commands like ``teleport``.

Usage:
    uv run kosh.py gateway status
    uv run kosh.py sandbox list
    uv run kosh.py teleport my-sandbox
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import click

_NOISE_PATTERNS = (
    "DEBUG openshell_sandbox::sandbox::linux::seccomp",
)


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    cwd = kwargs.get("cwd")
    env_overrides = kwargs.get("env")
    parts = [shlex.join(cmd)]
    if cwd:
        parts.append(f"(cwd={cwd})")
    if env_overrides:
        diff = {k: v for k, v in env_overrides.items() if os.environ.get(k) != v}
        if diff:
            env_str = " ".join(f"{k}={v}" for k, v in sorted(diff.items()))
            parts.append(f"(env: {env_str})")
    click.echo(f"+ {' '.join(parts)}", err=True)
    kwargs.setdefault("stdin", sys.stdin)
    kwargs.setdefault("stdout", sys.stdout)
    if "stderr" not in kwargs:
        proc = subprocess.Popen(cmd, stdin=kwargs.pop("stdin", sys.stdin),
                                stdout=kwargs.pop("stdout", sys.stdout),
                                stderr=subprocess.PIPE, text=True, **kwargs)
        for line in proc.stderr:
            if any(pat in line for pat in _NOISE_PATTERNS):
                continue
            sys.stderr.write(line)
        proc.wait()
        return subprocess.CompletedProcess(cmd, proc.returncode)
    return subprocess.run(cmd, **kwargs)


def _find_openshell() -> str:
    workspace_bin = pathlib.Path(__file__).resolve().parent.parent.parent / ".local" / "bin" / "openshell"
    if workspace_bin.is_file() and os.access(workspace_bin, os.X_OK):
        return str(workspace_bin)
    path = shutil.which("openshell")
    if path:
        return path
    click.echo("error: 'openshell' CLI not found in PATH", err=True)
    click.echo("Install it with: uv tool install -U openshell", err=True)
    sys.exit(1)


def _in_local_sandbox() -> bool:
    """Return True if running inside a kosh local sandbox."""
    return os.environ.get("KOSH_SANDBOX") == "1"


def _check_not_in_sandbox(cmd_name: str) -> None:
    """Exit with helpful message if running inside a local sandbox."""
    if _in_local_sandbox():
        click.echo(f"error: 'kosh {cmd_name}' cannot run inside a sandbox.", err=True)
        click.echo("  Exit the sandbox first (type 'exit'), then run from the host shell.", err=True)
        sys.exit(1)


OPENSHELL_PASSTHROUGH = [
    "gateway",
    "status",
    "forward",
    "logs",
    "policy",
    "settings",
    "provider",
    "inference",
    "doctor",
    "term",
    "ssh-proxy",
]


class KoshGroup(click.Group):
    """Click group that delegates unknown commands to the openshell CLI."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        if cmd_name in OPENSHELL_PASSTHROUGH:
            return _make_passthrough(cmd_name)
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        native = super().list_commands(ctx)
        return sorted(set(native + OPENSHELL_PASSTHROUGH))

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write("Usage: kosh <command> [args...]\n")

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_paragraph()
        formatter.write("Kagenti OpenShell CLI — all openshell commands plus kagenti extras.\n")



def _make_passthrough(name: str) -> click.Command:
    @click.command(
        name,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "allow_interspersed_args": False,
            "help_option_names": [],
        },
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def proxy(args: tuple[str, ...]) -> None:
        _check_not_in_sandbox(name)
        openshell = _find_openshell()
        cmd = [openshell, name, *args]
        click.echo(f"+ {shlex.join(cmd)}", err=True)
        sys.exit(_passthrough_exec(cmd))

    proxy.help = f"(passthrough) openshell {name}"
    return proxy


def _passthrough_exec(cmd: list[str]) -> int:
    """Execute an openshell command filtering seccomp noise from both streams.

    Uses pty for interactive commands (connect/term) so that seccomp noise
    printed via the PTY (stdout) is also filtered. Non-TTY environments
    fall back to Popen with stderr filtering.
    """
    import pty
    import select

    if not sys.stdin.isatty():
        proc = subprocess.Popen(
            cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        import threading

        def _filter_stderr():
            for line in proc.stderr:
                if any(pat in line for pat in _NOISE_PATTERNS):
                    continue
                sys.stderr.write(line)
                sys.stderr.flush()

        t = threading.Thread(target=_filter_stderr, daemon=True)
        t.start()
        for line in proc.stdout:
            if any(pat in line for pat in _NOISE_PATTERNS):
                continue
            sys.stdout.write(line)
            sys.stdout.flush()
        t.join(timeout=2)
        return proc.wait()

    # Interactive: use pty to intercept stdout (where seccomp noise appears)
    import termios
    import struct
    import fcntl
    import signal

    master_fd, slave_fd = pty.openpty()

    # Copy terminal size to slave pty
    if sys.stdout.isatty():
        win = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, b'\x00' * 8)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, win)

    proc = subprocess.Popen(
        cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True, preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    # Forward SIGWINCH to child
    def _resize(signum, frame):
        if sys.stdout.isatty():
            win = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, b'\x00' * 8)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, win)
            os.kill(proc.pid, signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, _resize)

    # Put terminal in raw mode
    old_attrs = termios.tcgetattr(sys.stdin)
    try:
        import tty
        tty.setraw(sys.stdin)

        noise_bytes = [pat.encode() for pat in _NOISE_PATTERNS]
        buf = b""

        while True:
            try:
                rlist, _, _ = select.select([sys.stdin, master_fd], [], [], 0.1)
            except (OSError, ValueError):
                break

            if sys.stdin in rlist:
                try:
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        break
                    os.write(master_fd, data)
                except OSError:
                    break

            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                except OSError:
                    break

                # Filter seccomp noise line-by-line
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if any(pat in line for pat in noise_bytes):
                        continue
                    os.write(sys.stdout.fileno(), line + b"\n")
                # Flush partial line (non-newline terminated output like prompts)
                if buf and b"\n" not in buf:
                    if not any(pat in buf for pat in noise_bytes):
                        os.write(sys.stdout.fileno(), buf)
                        buf = b""

            if proc.poll() is not None:
                # Drain remaining
                try:
                    remaining = os.read(master_fd, 4096)
                    if remaining:
                        for line in remaining.split(b"\n"):
                            if any(pat in line for pat in noise_bytes):
                                continue
                            if line:
                                os.write(sys.stdout.fileno(), line + b"\n")
                except OSError:
                    pass
                break

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, old_attrs)
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        os.close(master_fd)

    proc.wait()
    return proc.returncode


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _bold(text: str) -> str:
    """Wrap text in ANSI bold if stdout is a terminal."""
    if sys.stdout.isatty():
        return f"\033[1m{text}\033[0m"
    return text


class BoldHelpFormatter(click.HelpFormatter):
    """Click help formatter that bolds section headers, commands, and options like openshell."""

    def write_heading(self, heading: str) -> None:
        label = "FLAGS" if heading.lower() == "options" else heading.upper()
        self.write(f"\n{_bold(label)}\n")

    def write_usage(self, prog: str, args: str = "", prefix: str | None = None) -> None:
        self.write(f"{_bold('USAGE')}\n  {_bold(prog)} {args}\n")

    def write_dl(self, rows: list[tuple[str, str]], col_max: int = 30, col_spacing: int = 2) -> None:
        rows = [(_bold(term), help_text) for term, help_text in rows]
        super().write_dl(rows, col_max=col_max, col_spacing=col_spacing)


click.core.Context.formatter_class = BoldHelpFormatter


@click.group(cls=KoshGroup, context_settings=CONTEXT_SETTINGS)
@click.version_option(version="0.1.0-dev+96eee1dd", prog_name="kosh")
def cli() -> None:
    """kosh - Kagenti OpenShell CLI."""


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_MODEL = os.environ.get("KOSH_MODEL", "claude-opus-4-6")
LITELLM_BASE_URL = "https://ete-litellm.ai-models.vpc-int.res.ibm.com"
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent

DEFAULT_BINARIES = [
    "/usr/local/bin/claude",
    "/usr/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/curl",
    "/usr/bin/git",
    "/usr/lib/git-core/git-remote-http",
    "/usr/lib/git-core/git-remote-https",
]

BUILTIN_PROFILES: dict[str, dict] = {
    "claude-infra": {
        "builtin": True,
        "description": "Claude Code infrastructure (Anthropic API, statsig, sentry)",
        "endpoints": [
            {"host": "api.anthropic.com", "port": 443},
            {"host": "statsig.anthropic.com", "port": 443},
            {"host": "sentry.io", "port": 443},
            {"host": "platform.claude.com", "port": 443},
        ],
    },
    "web-search": {
        "builtin": True,
        "description": "Search engines (Google, Bing, DuckDuckGo)",
        "endpoints": [
            {"host": "google.com", "port": 443},
            {"host": "*.google.com", "port": 443},
            {"host": "*.googleapis.com", "port": 443},
            {"host": "bing.com", "port": 443},
            {"host": "*.bing.com", "port": 443},
            {"host": "duckduckgo.com", "port": 443},
            {"host": "*.duckduckgo.com", "port": 443},
        ],
    },
    "dev-tools": {
        "builtin": True,
        "description": "Developer resources (GitHub, Stack Overflow, npm, PyPI, docs)",
        "endpoints": [
            {"host": "github.com", "port": 443},
            {"host": "*.github.com", "port": 443},
            {"host": "*.githubusercontent.com", "port": 443},
            {"host": "stackoverflow.com", "port": 443},
            {"host": "*.stackoverflow.com", "port": 443},
            {"host": "*.stackexchange.com", "port": 443},
            {"host": "npmjs.com", "port": 443},
            {"host": "*.npmjs.com", "port": 443},
            {"host": "pypi.org", "port": 443},
            {"host": "*.pypi.org", "port": 443},
            {"host": "*.readthedocs.io", "port": 443},
            {"host": "*.docs.rs", "port": 443},
        ],
    },
    "ibm-litellm": {
        "builtin": True,
        "description": "IBM LiteLLM proxy",
        "endpoints": [
            {"host": "ete-litellm.ai-models.vpc-int.res.ibm.com", "port": 443},
        ],
    },
}


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), default="zsh")
def completions(shell: str) -> None:
    """Generate shell completions for kosh.

    Prints a completion script to stdout. Add to your shell profile:

    \b
        # zsh — add to ~/.zshrc
        eval "$(kosh completions zsh)"
    \b
        # bash — add to ~/.bashrc
        eval "$(kosh completions bash)"
    \b
        # fish — add to fish config
        kosh completions fish | source
    """
    from click.shell_completion import get_completion_class

    comp_cls = get_completion_class(shell)
    if comp_cls is None:
        click.echo(f"error: unsupported shell: {shell}", err=True)
        sys.exit(1)
    comp = comp_cls(cli, {}, "kosh", "_KOSH_COMPLETE")
    click.echo(comp.source())


# ---------------------------------------------------------------------------
# sandbox group — delegates to openshell but exposes subcommands for completion
# ---------------------------------------------------------------------------

_SANDBOX_SUBCOMMANDS = [
    "create", "get", "list", "delete", "exec", "connect",
    "upload", "download", "ssh-config", "provider", "sb",
]


class SandboxGroup(click.Group):
    """Sandbox group that delegates unknown subcommands to openshell sandbox."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        if cmd_name in _SANDBOX_SUBCOMMANDS:
            return _make_sandbox_subcommand(cmd_name)
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(_SANDBOX_SUBCOMMANDS)


def _make_sandbox_subcommand(subcmd: str) -> click.Command:
    @click.command(
        subcmd,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "allow_interspersed_args": False,
            "help_option_names": [],
        },
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def handler(args: tuple[str, ...]) -> None:
        _check_not_in_sandbox("sandbox")
        openshell = _find_openshell()
        cmd = [openshell, "sandbox", subcmd, *args]
        click.echo(f"+ {shlex.join(cmd)}", err=True)
        sys.exit(_passthrough_exec(cmd))

    handler.help = f"openshell sandbox {subcmd}"
    return handler


@cli.group("sandbox", cls=SandboxGroup, context_settings=CONTEXT_SETTINGS,
           invoke_without_command=True)
@click.pass_context
def sandbox_group(ctx: click.Context) -> None:
    """Manage OpenShell sandboxes (list, create, connect, exec, ...)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("name", default=None, required=False)
@click.option("--directory", "-d", default=None, hidden=True, help="[Deprecated] Use positional argument instead.")
@click.option("--watch", "-w", is_flag=True, default=False, help="After initial upload, watch for file changes and sync continuously.")
@click.option("--openshell-bin", default=None, help="Path to openshell binary.")
@click.option("--xdg-config-home", default=None, help="Override XDG_CONFIG_HOME for gateway config.")
@click.option("--connect/--no-connect", default=False, help="Connect to the sandbox after setup.")
@click.option("--custom-image", is_flag=True, default=False, help="Build sandbox from Dockerfile.sandbox (requires Docker).")
@click.option("--model", default=DEFAULT_MODEL, show_default=True, help="Claude model to set as ANTHROPIC_MODEL.")
@click.option("--allow-profile", multiple=True, help="Apply domain profile after teleport (repeatable).")
@click.option("--reapply-allowlist/--no-reapply-allowlist", default=True, help="Reapply saved allowlists from config.")
def teleport(name: str | None, directory: str | None, watch: bool, openshell_bin: str | None, xdg_config_home: str | None, connect: bool, custom_image: bool, model: str, allow_profile: tuple[str, ...], reapply_allowlist: bool) -> None:
    """Set up and sync a project into an OpenShell sandbox.

    Creates the litellm provider if needed, creates a sandbox named after the
    project directory, uploads local files, and configures .bashrc inside the
    sandbox.

    If no NAME is specified, uses the last local sandbox from kosh config.
    NAME can be a sandbox name, a directory path, or '.' for current directory.

    Use --watch (-w) to keep syncing file changes after the initial upload.

    Examples:

    \b
        kosh teleport
        kosh teleport my-project
        kosh teleport .
        kosh teleport my-project --connect
        kosh teleport my-project -w
    """
    _check_not_in_sandbox("teleport")

    # Merge positional NAME and deprecated --directory/-d
    target = name or directory

    if target:
        dir_path = pathlib.Path(target).resolve()
        if not dir_path.is_dir():
            dir_path = (pathlib.Path.cwd() / target).resolve()
        if not dir_path.is_dir():
            config_dir = _kosh_config_dir()
            metadata = _read_metadata(config_dir)
            sb_info = metadata.get("sandboxes", {}).get(target, {})
            sb_path = sb_info.get("path")
            if sb_path and pathlib.Path(sb_path).is_dir():
                dir_path = pathlib.Path(sb_path)
        if not dir_path.is_dir():
            click.echo(f"error: '{target}' not found as directory or sandbox name.", err=True)
            sys.exit(1)
        cwd = str(dir_path)
    else:
        config_dir = _kosh_config_dir()
        last = _load_last_sandbox(config_dir)
        if last and pathlib.Path(last).is_dir():
            cwd = last
            click.echo(f"Using last local sandbox: {cwd}")
        else:
            click.echo("error: no sandbox specified and no last local sandbox found.", err=True)
            click.echo("Usage: kosh teleport NAME", err=True)
            sys.exit(1)

    cwd_path = pathlib.Path(cwd).resolve()
    sandbox_name = cwd_path.name
    osbin = openshell_bin or _find_openshell()

    click.echo(f"Teleporting '{sandbox_name}' from {cwd_path}")
    _teleport_impl(sandbox_name, cwd_path, osbin, model, custom_image)

    # Apply domain allowlist profiles after successful teleport
    config_dir = _kosh_config_dir()
    all_profiles = _read_profiles(config_dir)
    metadata = _read_metadata(config_dir)
    sb = metadata["sandboxes"].setdefault(sandbox_name, {})

    profiles_to_apply: list[str] = []
    if allow_profile:
        profiles_to_apply = list(allow_profile)
        applied = sb.setdefault("applied_profiles", [])
        for p in profiles_to_apply:
            if p not in applied:
                applied.append(p)
        _write_metadata(config_dir, metadata)
    elif reapply_allowlist:
        profiles_to_apply = sb.get("applied_profiles", [])

    if profiles_to_apply:
        endpoints: list[dict] = []
        for pname in profiles_to_apply:
            p = all_profiles.get(pname)
            if p:
                endpoints.extend(p.get("endpoints", []))
                click.echo(f"  Applying profile '{pname}' ({len(p.get('endpoints', []))} endpoints)")
            else:
                click.echo(f"  Warning: profile '{pname}' not found, skipping.", err=True)
        for ep in sb.get("allowed_domains", []):
            if ep not in endpoints:
                endpoints.append(ep)
        if endpoints:
            _apply_endpoints(sandbox_name, endpoints)

    if watch:
        _watch_and_sync(sandbox_name, cwd_path, osbin)
    elif connect:
        result = _run([osbin, "sandbox", "connect", sandbox_name], cwd=str(cwd_path))
        sys.exit(result.returncode)


@cli.command()
@click.argument("name", default=None, required=False)
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be downloaded without writing files.")
@click.option("--force", is_flag=True, default=False, help="Overwrite files with uncommitted local changes.")
@click.option("--path", "specific_path", default=None, help="Pull only a specific file or directory.")
@click.option("--openshell-bin", default=None, help="Path to openshell binary.")
def pull(name: str | None, dry_run: bool, force: bool, specific_path: str | None, openshell_bin: str | None) -> None:
    """Pull files from a remote OpenShell sandbox back to local directory.

    Downloads changed files from the remote sandbox. By default, skips files
    that have uncommitted local changes (use --force to overwrite).

    NAME is the sandbox name. If not specified, uses the last teleported sandbox.

    Examples:

    \b
        kosh pull
        kosh pull my-project
        kosh pull my-project --dry-run
        kosh pull my-project --force
        kosh pull my-project --path src/main.py
    """
    _check_not_in_sandbox("pull")

    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)

    # Resolve sandbox name
    if name:
        sandbox_name = name
    else:
        last = _load_last_sandbox(config_dir)
        if last:
            sandbox_name = pathlib.Path(last).name
        else:
            click.echo("error: no sandbox specified and no last teleported sandbox found.", err=True)
            click.echo("Usage: kosh pull NAME", err=True)
            sys.exit(1)

    # Look up stored path mapping
    sb_info = metadata.get("sandboxes", {}).get(sandbox_name, {})
    local_path_str = sb_info.get("path")
    remote_path_str = sb_info.get("remote_path")

    if not local_path_str or not remote_path_str:
        click.echo(f"error: no teleport mapping found for '{sandbox_name}'.", err=True)
        click.echo("Run 'kosh teleport' first to establish the local↔remote mapping.", err=True)
        sys.exit(1)

    local_dir = pathlib.Path(local_path_str)
    if not local_dir.is_dir():
        click.echo(f"error: local directory '{local_dir}' does not exist.", err=True)
        sys.exit(1)

    osbin = openshell_bin or _find_openshell()
    action = "Dry-run pull" if dry_run else "Pulling"
    click.echo(f"{action} from sandbox '{sandbox_name}' → {local_dir}")

    _pull_impl(sandbox_name, local_dir, remote_path_str, osbin,
               dry_run=dry_run, force=force, specific_path=specific_path)


def _find_support_file(name: str) -> pathlib.Path:
    """Find a support file: check SCRIPT_DIR first, then ~/.config/kosh/."""
    candidate = SCRIPT_DIR / name
    if candidate.exists():
        return candidate
    config_candidate = (pathlib.Path.home() / ".config" / "kosh" / name)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        config_candidate = pathlib.Path(xdg) / "kosh" / name
    if config_candidate.exists():
        return config_candidate
    return candidate


SANDBOX_SH = _find_support_file("sandbox.sh")

_SENSITIVE_PATTERNS = [
    ".config/", "openshell/", "oidc_token.json", "token.json",
    "edge_token.json", "rossconfig.json", "*.key", "*.crt", "*.pem",
]


def _is_sensitive(rel_path: str) -> bool:
    """Check if a relative path matches sensitive patterns."""
    parts = pathlib.PurePosixPath(rel_path).parts
    for pat in _SENSITIVE_PATTERNS:
        if pat.endswith("/"):
            if parts[0] == pat.rstrip("/"):
                return True
        elif "*" in pat:
            if fnmatch.fnmatch(parts[-1], pat):
                return True
        else:
            if rel_path == pat or parts[-1] == pat:
                return True
    return False


def _is_gitignored(path: pathlib.Path, repo_root: pathlib.Path) -> bool:
    """Check if a file is gitignored (using git check-ignore)."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(repo_root), capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Teleport helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _openshell_exec(openshell: str, args: list[str], quiet: bool = False,
                    capture: bool = False) -> subprocess.CompletedProcess:
    """Run openshell with args, filtering seccomp noise from stderr."""
    cmd = [openshell, *args]
    if not quiet:
        click.echo(f"+ {shlex.join(cmd)}", err=True)
    if capture:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate()
        filtered_err = "\n".join(
            l for l in stderr.splitlines() if not any(p in l for p in _NOISE_PATTERNS)
        )
        if filtered_err and not quiet:
            sys.stderr.write(filtered_err + "\n")
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=filtered_err)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if any(p in line for p in _NOISE_PATTERNS):
            continue
        sys.stdout.write(line)
    for line in proc.stderr:
        if any(p in line for p in _NOISE_PATTERNS):
            continue
        sys.stderr.write(line)
    proc.wait()
    return subprocess.CompletedProcess(cmd, proc.returncode)


def _openshell_pipe_stdin(openshell: str, args: list[str], stdin_text: str,
                          quiet: bool = False) -> subprocess.CompletedProcess:
    """Run openshell with text piped to stdin (avoids newlines in args)."""
    cmd = [openshell, *args]
    if not quiet:
        click.echo(f"+ {shlex.join(cmd)} (stdin piped)", err=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(input=stdin_text)
    if stdout:
        for line in stdout.splitlines():
            if any(p in line for p in _NOISE_PATTERNS):
                continue
            sys.stdout.write(line + "\n")
    if stderr:
        for line in stderr.splitlines():
            if any(p in line for p in _NOISE_PATTERNS):
                continue
            sys.stderr.write(line + "\n")
    return subprocess.CompletedProcess(cmd, proc.returncode)


def _sandbox_exists(openshell: str, name: str) -> bool:
    """Check if sandbox exists by parsing openshell sandbox list."""
    result = _openshell_exec(openshell, ["sandbox", "list"], quiet=True, capture=True)
    if result.returncode != 0:
        return False
    clean = _ANSI_RE.sub("", result.stdout or "")
    for line in clean.splitlines():
        fields = line.split()
        if fields and fields[0] == name:
            return True
    return False


def _wait_sandbox_ready(openshell: str, name: str, timeout: int = 60) -> None:
    """Poll until sandbox reaches Ready phase. Raises SystemExit on timeout."""
    click.echo(f"  Waiting for sandbox '{name}' to be ready...")
    for i in range(1, timeout + 1):
        result = _openshell_exec(openshell, ["sandbox", "list"], quiet=True, capture=True)
        clean = _ANSI_RE.sub("", result.stdout or "")
        for line in clean.splitlines():
            fields = line.split()
            if fields and fields[0] == name and fields[-1] == "Ready":
                probe = _openshell_exec(openshell, ["sandbox", "exec", "--name", name,
                                                    "--no-tty", "--", "true"], quiet=True, capture=True)
                if probe.returncode == 0:
                    click.echo(f"  Sandbox '{name}' is ready.")
                    return
        if i == timeout:
            click.echo(f"error: sandbox '{name}' did not become ready within {timeout}s", err=True)
            sys.exit(1)
        if i % 5 == 0:
            click.echo(f"  Waiting... ({i}s)")
        time.sleep(1)


def _ensure_gitignore(project_dir: pathlib.Path) -> None:
    """Add sensitive patterns to .gitignore if not already present."""
    gitignore = project_dir / ".gitignore"
    changed = False
    for pat in _SENSITIVE_PATTERNS:
        existing = gitignore.read_text() if gitignore.exists() else ""
        if pat not in existing.splitlines():
            with gitignore.open("a") as f:
                f.write(pat + "\n")
            changed = True
    if changed:
        click.echo("  Updated .gitignore to exclude sensitive files from upload.")


def _warn_sensitive_skips(project_dir: pathlib.Path) -> None:
    """Print SKIP warnings for sensitive files/dirs that won't be uploaded."""
    for pat in _SENSITIVE_PATTERNS:
        if pat.endswith("/"):
            d = project_dir / pat.rstrip("/")
            if d.is_dir():
                click.echo(f"  SKIP (sensitive): {d}/")
        elif "*" in pat:
            for f in project_dir.glob(pat):
                click.echo(f"  SKIP (sensitive): {f}")
        else:
            f = project_dir / pat
            if f.is_file():
                click.echo(f"  SKIP (sensitive): {f}")


def _teleport_impl(sandbox_name: str, project_dir: pathlib.Path, openshell: str,
                   model: str, custom_image: bool) -> None:
    """Full teleport implementation: provider, create/detect sandbox, setup, upload."""

    # Step 1: Ensure litellm provider exists
    click.echo("Checking for litellm provider...")
    result = _openshell_exec(openshell, ["provider", "list"], quiet=True, capture=True)
    if "litellm" in (result.stdout or ""):
        click.echo("  litellm provider found.")
    else:
        click.echo("  litellm provider not found, creating...")
        token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not token:
            click.echo("error: ANTHROPIC_AUTH_TOKEN is not set.", err=True)
            click.echo("Export it before running this command:", err=True)
            click.echo("  export ANTHROPIC_AUTH_TOKEN=<your-token>", err=True)
            sys.exit(1)
        cred_args = ["--credential", f"ANTHROPIC_AUTH_TOKEN={token}"]
        bob_key = os.environ.get("BOBSHELL_API_KEY")
        if bob_key:
            cred_args += ["--credential", f"BOBSHELL_API_KEY={bob_key}"]
        _openshell_exec(openshell, ["provider", "create", "--name", "litellm",
                                    "--type", "generic", *cred_args])
        click.echo("  litellm provider created.")

    # Step 2: Verify .claude dir exists
    if not (project_dir / ".claude").is_dir():
        click.echo(f"error: no .claude directory found in {project_dir}", err=True)
        click.echo("Run this command from a project directory that has a .claude/ folder.", err=True)
        sys.exit(1)

    click.echo(f"Project directory: {project_dir}")
    click.echo(f"Sandbox name: {sandbox_name}")

    # Step 3: Create sandbox or skip if exists
    click.echo(f"Checking for existing sandbox '{sandbox_name}'...")
    if _sandbox_exists(openshell, sandbox_name):
        click.echo(f"  Sandbox '{sandbox_name}' already exists.")
    else:
        click.echo(f"  Creating sandbox '{sandbox_name}'...")
        policy_file = _find_support_file("litellm_sandbox_policy.yaml")
        if not policy_file.exists():
            click.echo(f"error: policy file not found: {policy_file}", err=True)
            sys.exit(1)

        create_args = ["sandbox", "create", "--name", sandbox_name,
                       "--policy", str(policy_file), "--provider", "litellm"]
        if custom_image:
            dockerfile = _find_support_file("Dockerfile.sandbox")
            if dockerfile.exists():
                click.echo(f"  Using custom Dockerfile: {dockerfile}")
                create_args += ["--from", str(dockerfile)]
        create_args += ["--no-tty", "--", "true"]
        _openshell_exec(openshell, create_args)
        click.echo(f"  Sandbox '{sandbox_name}' created.")

        # Wait for Ready
        _wait_sandbox_ready(openshell, sandbox_name)

        # Step 4: One-time .bashrc setup
        click.echo("  Configuring sandbox environment...")
        bashrc_content = f"""\
export PATH="$HOME/.local/bin:$PATH"
export PATH="/sandbox/.npm-global/bin:$PATH"
export ANTHROPIC_BASE_URL="{LITELLM_BASE_URL}"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
export NODE_NO_WARNINGS=1
export ANTHROPIC_MODEL="{model}"
export HOME={project_dir}
cd "{project_dir}" 2>/dev/null || true
alias kosh="echo \\"kosh is not available inside the sandbox. To run kosh commands, exit the sandbox (type exit) or use another terminal.\\""
"""
        _openshell_pipe_stdin(openshell,
                             ["sandbox", "exec", "--name", sandbox_name,
                              "--no-tty", "--", "sh", "-c", "cat >> /sandbox/.bashrc"],
                             bashrc_content)

        profile_line = f'cd "{project_dir}" 2>/dev/null || true\n'
        _openshell_pipe_stdin(openshell,
                             ["sandbox", "exec", "--name", sandbox_name,
                              "--no-tty", "--", "sh", "-c", "cat >> /sandbox/.profile"],
                             profile_line)
        click.echo("  Environment configured.")

        # Step 5: One-time Bob install
        click.echo("\n  Installing Bob shell...")
        bob_install = _find_support_file("bob-install.sh")
        if not bob_install.exists():
            click.echo(f"  ERROR: {bob_install} not found", err=True)
            click.echo("  Trying official installer as fallback...", err=True)
            _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                        "--no-tty", "--", "bash", "-c",
                                        "curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash"],
                            quiet=True)
        else:
            _openshell_exec(openshell, ["sandbox", "upload", sandbox_name,
                                        str(bob_install), "/tmp/"])
            result = _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                                  "--no-tty", "--", "bash", "/tmp/bob-install.sh"])
            if result.returncode == 0:
                click.echo("  Bob installed.")
            else:
                click.echo("  WARNING: Bob install failed.", err=True)
                _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                            "--no-tty", "--", "bash", "-c",
                                            "curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash"],
                                quiet=True)

    # Step 6: Wait for ready (existing sandboxes may be restarting)
    _wait_sandbox_ready(openshell, sandbox_name)

    # Step 7: Upload files
    # Remove dangling symlinks
    for root, dirs, files in os.walk(project_dir):
        for name in files:
            fp = pathlib.Path(root) / name
            if fp.is_symlink() and not fp.exists():
                fp.unlink()

    _ensure_gitignore(project_dir)
    _warn_sensitive_skips(project_dir)

    parent_dir = str(project_dir.parent)
    click.echo(f"Uploading files from {project_dir} to sandbox:{project_dir} ...")
    _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                "--", "mkdir", "-p", parent_dir])
    _openshell_exec(openshell, ["sandbox", "upload", sandbox_name,
                                str(project_dir), parent_dir + "/"])
    if (project_dir / ".claude").is_dir():
        click.echo("  Uploading .claude/ (gitignored, using --no-git-ignore)...")
        _openshell_exec(openshell, ["sandbox", "upload", "--no-git-ignore", sandbox_name,
                                    str(project_dir / ".claude"), str(project_dir) + "/"])
    click.echo("  Files uploaded.")

    # Store teleport mapping for kosh pull
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    sb = metadata["sandboxes"].setdefault(sandbox_name, {})
    sb["path"] = str(project_dir)
    sb["remote_path"] = str(project_dir)
    _write_metadata(config_dir, metadata)

    click.echo(f"\nDone. Sandbox '{sandbox_name}' is ready.")
    click.echo(f"\nTo connect:")
    click.echo(f"  kosh sandbox connect {sandbox_name}")


def _pull_impl(sandbox_name: str, local_dir: pathlib.Path, remote_path: str,
               openshell: str, dry_run: bool = False, force: bool = False,
               specific_path: str | None = None) -> None:
    """Pull files from remote sandbox back to local directory."""
    # List remote files
    find_target = remote_path
    if specific_path:
        find_target = str(pathlib.PurePosixPath(remote_path) / specific_path)

    result = _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                         "--no-tty", "--",
                                         "find", find_target, "-type", "f"],
                             quiet=True, capture=True)
    if result.returncode != 0:
        click.echo(f"error: could not list files in remote sandbox '{sandbox_name}'.", err=True)
        sys.exit(1)

    remote_files: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("/"):
            continue
        rel = os.path.relpath(line, remote_path)
        if rel.startswith(".git/") or rel == ".git":
            continue
        if _is_sensitive(rel):
            continue
        remote_files.append(rel)

    if not remote_files:
        click.echo("No files to pull.")
        return

    # Get git-dirty files
    git_dirty: set[str] = set()
    if (local_dir / ".git").exists():
        proc = subprocess.run(["git", "diff", "--name-only"],
                              cwd=str(local_dir), capture_output=True, text=True)
        if proc.returncode == 0:
            git_dirty.update(l for l in proc.stdout.splitlines() if l.strip())
        proc = subprocess.run(["git", "diff", "--cached", "--name-only"],
                              cwd=str(local_dir), capture_output=True, text=True)
        if proc.returncode == 0:
            git_dirty.update(l for l in proc.stdout.splitlines() if l.strip())

    # Classify files
    to_download: list[tuple[str, str]] = []  # (rel_path, reason)
    skipped_dirty: list[str] = []
    unchanged: int = 0

    for rel in remote_files:
        local_file = local_dir / rel
        if rel in git_dirty and not force:
            skipped_dirty.append(rel)
            continue
        if not local_file.exists():
            to_download.append((rel, "new"))
        else:
            to_download.append((rel, "updated"))

    if dry_run:
        if to_download:
            click.echo(f"Would download: {len(to_download)} file(s)")
            for rel, reason in to_download:
                click.echo(f"  {reason:8s}  {rel}")
        if skipped_dirty:
            click.echo(f"Skipped (local changes): {len(skipped_dirty)} file(s)")
            for rel in skipped_dirty:
                click.echo(f"  dirty:    {rel}")
        if not to_download and not skipped_dirty:
            click.echo("Nothing to pull (all files unchanged).")
        return

    # Download via tarball (handles binary files, single round-trip)
    # Create tar in /sandbox/ (within openshell download workspace)
    tar_remote = "/sandbox/.kosh-pull.tar.gz"
    file_list = [rel for rel, _ in to_download]

    # Build tar command: tar czf /sandbox/.kosh-pull.tar.gz -C <remote_path> file1 file2 ...
    tar_cmd = ["tar", "czf", tar_remote, "-C", remote_path] + file_list
    result = _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                         "--no-tty", "--"] + tar_cmd, quiet=True)
    if result.returncode != 0:
        click.echo("error: failed to create tarball in remote sandbox.", err=True)
        sys.exit(1)

    # Download tarball to local temp location
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        dl_result = subprocess.run(
            [openshell, "sandbox", "download", sandbox_name, tar_remote, tmp + "/"],
            capture_output=True, text=True, timeout=60,
        )
        if dl_result.returncode != 0:
            click.echo(f"error: failed to download tarball: {dl_result.stderr.strip()}", err=True)
            sys.exit(1)

        # Extract tarball into local_dir
        tar_local = tmp_path / ".kosh-pull.tar.gz"
        with tarfile.open(tar_local, "r:gz") as tf:
            tf.extractall(path=str(local_dir))

    # Clean up remote tarball
    _openshell_exec(openshell, ["sandbox", "exec", "--name", sandbox_name,
                                "--no-tty", "--", "rm", "-f", tar_remote], quiet=True)

    downloaded = len(file_list)
    for rel, reason in to_download:
        click.echo(f"  {reason:8s}  {rel}")

    # Summary
    parts = [f"Pulled {downloaded} file(s)"]
    if skipped_dirty:
        parts.append(f"skipped {len(skipped_dirty)} (dirty)")
        for rel in skipped_dirty:
            click.echo(f"  warning: skipped '{rel}' (uncommitted local changes)", err=True)
        click.echo("  hint: use --force to overwrite, or git stash/commit first", err=True)
    click.echo(", ".join(parts) + ".")


def _scan_mtimes(directory: pathlib.Path) -> dict[str, float]:
    """Scan all files and return {relative_path: mtime}."""
    mtimes: dict[str, float] = {}
    for root, dirs, files in os.walk(directory):
        root_path = pathlib.Path(root)
        rel_root = root_path.relative_to(directory)
        # Skip hidden dirs and common noise
        dirs[:] = [d for d in dirs if not d.startswith(".") or d == ".claude"]
        for f in files:
            if f.startswith("."):
                continue
            rel = str(rel_root / f) if str(rel_root) != "." else f
            if _is_sensitive(rel):
                continue
            fp = root_path / f
            try:
                mtimes[rel] = fp.stat().st_mtime
            except OSError:
                pass
    # Also scan .claude/ explicitly
    claude_dir = directory / ".claude"
    if claude_dir.is_dir():
        for root, dirs, files in os.walk(claude_dir):
            root_path = pathlib.Path(root)
            rel_root = root_path.relative_to(directory)
            for f in files:
                rel = str(rel_root / f)
                fp = root_path / f
                try:
                    mtimes[rel] = fp.stat().st_mtime
                except OSError:
                    pass
    return mtimes


def _watch_and_sync(sandbox_name: str, directory: pathlib.Path, openshell: str,
                    interval: float = 2.0) -> None:
    """Watch directory for changes and upload modified files to remote sandbox."""
    click.echo(f"\nWatching {directory} for changes (Ctrl+C to stop)...")
    click.echo(f"  Sandbox: {sandbox_name}")
    click.echo(f"  Interval: {interval}s\n")

    prev_mtimes = _scan_mtimes(directory)
    heartbeat_count = 0

    try:
        while True:
            time.sleep(interval)
            curr_mtimes = _scan_mtimes(directory)

            changed: list[str] = []
            for rel, mtime in curr_mtimes.items():
                if rel not in prev_mtimes or prev_mtimes[rel] < mtime:
                    changed.append(rel)

            deleted = [r for r in prev_mtimes if r not in curr_mtimes]

            if changed:
                heartbeat_count = 0
                click.echo(f"\n[{time.strftime('%H:%M:%S')}] {len(changed)} file(s) changed:")
                for rel in changed:
                    local_path = directory / rel
                    remote_dir = str(directory / pathlib.Path(rel).parent)
                    click.echo(f"  uploading: {rel}")
                    cmd = [openshell, "sandbox", "upload", sandbox_name,
                           str(local_path), remote_dir + "/"]
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode != 0:
                        stderr = proc.stderr.strip()
                        if stderr:
                            click.echo(f"    error: {stderr}", err=True)
                click.echo(f"  synced {len(changed)} file(s).")
            elif deleted:
                heartbeat_count = 0
                click.echo(f"\n[{time.strftime('%H:%M:%S')}] {len(deleted)} file(s) deleted locally (not removed from remote)")
            else:
                heartbeat_count += 1
                if heartbeat_count % 5 == 0:
                    click.echo(".", nl=False)
                    sys.stdout.flush()

            prev_mtimes = curr_mtimes

    except KeyboardInterrupt:
        click.echo(f"\n\nWatch stopped.")


def _kosh_config_dir() -> pathlib.Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".config"
    return base / "kosh"


def _read_metadata(config_dir: pathlib.Path) -> dict:
    meta_file = config_dir / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {"sandboxes": {}}


def _write_metadata(config_dir: pathlib.Path, metadata: dict) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    meta_file = config_dir / "metadata.json"
    meta_file.write_text(json.dumps(metadata, indent=2) + "\n")


def _save_last_sandbox(config_dir: pathlib.Path, sandbox_dir: pathlib.Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "last_local_sandbox").write_text(str(sandbox_dir) + "\n")


def _load_last_sandbox(config_dir: pathlib.Path) -> str | None:
    last_file = config_dir / "last_local_sandbox"
    if last_file.exists():
        return last_file.read_text().strip()
    return None


def _read_profiles(config_dir: pathlib.Path) -> dict[str, dict]:
    """Merge built-in profiles with user-defined profiles from profiles.json."""
    profiles = dict(BUILTIN_PROFILES)
    pfile = config_dir / "profiles.json"
    if pfile.exists():
        data = json.loads(pfile.read_text())
        for name, p in data.get("profiles", {}).items():
            if name not in BUILTIN_PROFILES:
                profiles[name] = p
    return profiles


def _write_profiles(config_dir: pathlib.Path, user_profiles: dict[str, dict]) -> None:
    """Write user-defined profiles to profiles.json."""
    config_dir.mkdir(parents=True, exist_ok=True)
    pfile = config_dir / "profiles.json"
    pfile.write_text(json.dumps({"version": 1, "profiles": user_profiles}, indent=2) + "\n")


def _resolve_sandbox_name(sandbox: str | None) -> str:
    """Resolve sandbox name from option or last-used metadata."""
    if sandbox:
        return sandbox
    config_dir = _kosh_config_dir()
    last = _load_last_sandbox(config_dir)
    if last:
        return pathlib.Path(last).name
    click.echo("error: no --sandbox specified and no last sandbox found.", err=True)
    sys.exit(1)


def _apply_endpoints(sandbox_name: str, endpoints: list[dict], binaries: list[str] | None = None, wait: bool = True, all_binaries: bool = False) -> int:
    """Call openshell policy update to add endpoints to a sandbox. Returns exit code."""
    if not endpoints:
        return 0
    openshell = _find_openshell()
    cmd = [openshell, "policy", "update", sandbox_name]
    for ep in endpoints:
        host = ep["host"]
        port = ep.get("port", 443)
        cmd.extend(["--add-endpoint", f"{host}:{port}:full"])
    if not all_binaries:
        bins = binaries or DEFAULT_BINARIES
        for b in bins:
            cmd.extend(["--binary", b])
    if wait:
        cmd.append("--wait")
    result = _run(cmd)
    return result.returncode


def _run_sandbox_sh(sandbox_dir: pathlib.Path) -> None:
    if not SANDBOX_SH.exists():
        click.echo(f"error: sandbox.sh not found at {SANDBOX_SH}", err=True)
        sys.exit(1)
    env = {**os.environ, "SANDBOX_DIR": str(sandbox_dir.parent)}
    result = _run(["bash", str(SANDBOX_SH), "zsh"], cwd=str(sandbox_dir), env=env)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# kosh allow — domain allowlist management
# ---------------------------------------------------------------------------


@cli.group(context_settings=CONTEXT_SETTINGS)
def allow() -> None:
    """Manage domain allowlists for OpenShell sandboxes."""


@allow.command("add")
@click.argument("domains", nargs=-1, required=False)
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
@click.option("--port", "-p", default=443, type=int, show_default=True, help="Port to allow.")
@click.option("--binary", "-b", multiple=True, help="Binary paths (defaults to claude + node + curl + git).")
@click.option("--all-binaries", "-A", is_flag=True, default=False, help="Allow all binaries (no binary restriction).")
@click.option("--no-wait", is_flag=True, default=False, help="Don't wait for policy reload.")
@click.option("--no-save", is_flag=True, default=False, help="Don't persist domains to config.")
@click.option("--from-file", "-f", type=click.Path(exists=True), default=None, help="Read domains from file (one per line).")
@click.option("--from-json", "-j", type=click.Path(exists=False), default=None, help="Read from JSON (output of 'allow denied --json'). Use '-' for stdin.")
def allow_add(domains: tuple[str, ...], sandbox: str | None, port: int, binary: tuple[str, ...], all_binaries: bool, no_wait: bool, no_save: bool, from_file: str | None, from_json: str | None) -> None:
    """Allow domains on a running sandbox.

    Calls openshell policy update to add endpoints. Saves domains to
    per-sandbox config by default so they can be reapplied later.

    Domains can be space-separated args, comma-separated, read from a file,
    or piped as JSON from 'kosh allow denied --json'.

    Examples:

    \b
        kosh allow add github.com stackoverflow.com
        kosh allow add github.com,stackoverflow.com,pypi.org
        kosh allow add github.com -A              # all binaries, no restriction
        kosh allow add github.com -b /usr/bin/git # specific binary only
        kosh allow add --from-file domains.txt --sandbox test
        kosh allow denied --json | kosh allow add --from-json - --sandbox test
    """
    import json as json_mod

    all_endpoints: list[dict] = []
    for d in domains:
        for part in d.split(","):
            part = part.strip()
            if part:
                all_endpoints.append({"host": part, "port": port})
    if from_file:
        with open(from_file) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    for part in line.split(","):
                        part = part.strip()
                        if part:
                            all_endpoints.append({"host": part, "port": port})
    if from_json:
        if from_json == "-":
            data = json_mod.load(sys.stdin)
        else:
            with open(from_json) as fh:
                data = json_mod.load(fh)
        if not isinstance(data, list):
            raise click.UsageError("--from-json expects a JSON array of {host, port} objects.")
        for item in data:
            host = item.get("host")
            p = item.get("port", 443)
            if host:
                all_endpoints.append({"host": host, "port": int(p)})
    if not all_endpoints:
        raise click.UsageError("Provide domains as arguments, comma-separated, via --from-file, or --from-json.")
    name = _resolve_sandbox_name(sandbox)
    endpoints = all_endpoints
    bins = list(binary) if binary else None
    rc = _apply_endpoints(name, endpoints, binaries=bins, wait=not no_wait, all_binaries=all_binaries)
    if rc != 0:
        sys.exit(rc)
    click.echo(f"Allowed {len(endpoints)} domain(s) on sandbox '{name}'.")
    if not no_save:
        config_dir = _kosh_config_dir()
        metadata = _read_metadata(config_dir)
        sb = metadata["sandboxes"].setdefault(name, {})
        existing = sb.setdefault("allowed_domains", [])
        for ep in endpoints:
            if ep not in existing:
                existing.append(ep)
        _write_metadata(config_dir, metadata)


@allow.command("list")
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
def allow_list(sandbox: str | None) -> None:
    """Show allowed domains for a sandbox.

    Examples:

    \b
        kosh allow list
        kosh allow list --sandbox test
    """
    name = _resolve_sandbox_name(sandbox)
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    sb = metadata.get("sandboxes", {}).get(name, {})
    profiles = sb.get("applied_profiles", [])
    domains = sb.get("allowed_domains", [])

    click.echo(f"Sandbox: {name}")
    if profiles:
        click.echo(f"Profiles: {', '.join(profiles)}")
    if domains:
        click.echo("Domains:")
        for ep in domains:
            click.echo(f"  {ep['host']}:{ep.get('port', 443)}")
    if not profiles and not domains:
        click.echo("  (no saved allowlists)")


@allow.command("remove")
@click.argument("domains", nargs=-1, required=True)
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
def allow_remove(domains: tuple[str, ...], sandbox: str | None) -> None:
    """Remove domains from saved config (does NOT revoke from running sandbox).

    OpenShell policy update is additive-only. This command removes domains
    from the stored config so they won't be reapplied on next reapply.
    """
    name = _resolve_sandbox_name(sandbox)
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    sb = metadata.get("sandboxes", {}).get(name, {})
    existing = sb.get("allowed_domains", [])
    removed = 0
    for d in domains:
        matches = [ep for ep in existing if ep["host"] == d]
        for m in matches:
            existing.remove(m)
            removed += 1
    _write_metadata(config_dir, metadata)
    click.echo(f"Removed {removed} domain(s) from saved config for '{name}'.")
    if removed:
        click.echo("Note: domains are NOT revoked from the running sandbox (policy is additive).")


@allow.command("reapply")
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
def allow_reapply(sandbox: str | None) -> None:
    """Reapply all saved allowlists to a sandbox.

    Useful after recreating a sandbox — applies all stored profiles and
    individual domains.
    """
    name = _resolve_sandbox_name(sandbox)
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    sb = metadata.get("sandboxes", {}).get(name, {})
    all_profiles = _read_profiles(config_dir)

    endpoints: list[dict] = []
    for pname in sb.get("applied_profiles", []):
        profile = all_profiles.get(pname)
        if profile:
            endpoints.extend(profile["endpoints"])
            click.echo(f"  Profile '{pname}': {len(profile['endpoints'])} endpoint(s)")
    for ep in sb.get("allowed_domains", []):
        if ep not in endpoints:
            endpoints.append(ep)

    if not endpoints:
        click.echo(f"No saved allowlists for sandbox '{name}'.")
        return

    click.echo(f"Reapplying {len(endpoints)} endpoint(s) to '{name}'...")
    rc = _apply_endpoints(name, endpoints)
    if rc != 0:
        sys.exit(rc)
    click.echo("Done.")


@allow.command("denied")
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
@click.option("--since", default="1h", help="How far back to look (e.g. 5m, 1h, 24h).")
@click.option("--apply", "do_apply", is_flag=True, default=False, help="Immediately allow all denied domains.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON list.")
def allow_denied(sandbox: str | None, since: str, do_apply: bool, as_json: bool) -> None:
    """Show domains denied by the sandbox proxy.

    Reads OCSF logs for DENIED network events and extracts unique
    host:port pairs. Use --apply to immediately allow them all.

    Examples:

    \b
        kosh allow denied --sandbox test
        kosh allow denied --since 24h --apply
        kosh allow denied --json | jq .
    """
    import json as json_mod
    import re

    name = _resolve_sandbox_name(sandbox)
    openshell = _find_openshell()
    result = subprocess.run(
        [openshell, "logs", name, "-n", "200", "--source", "sandbox", "--since", since],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo(f"error: failed to read logs: {result.stderr.strip()}", err=True)
        sys.exit(1)

    pattern = re.compile(r"DENIED\s+\S+\s+->\s+(\S+):(\d+)")
    denied: dict[str, int] = {}
    for line in result.stdout.splitlines():
        m = pattern.search(line)
        if m:
            host, port = m.group(1), int(m.group(2))
            key = f"{host}:{port}"
            denied[key] = denied.get(key, 0) + 1

    if not denied:
        click.echo(f"No denied connections found in last {since} for sandbox '{name}'.")
        return

    if as_json:
        items = [{"host": k.rsplit(":", 1)[0], "port": int(k.rsplit(":", 1)[1]), "count": v} for k, v in sorted(denied.items())]
        click.echo(json_mod.dumps(items, indent=2))
    else:
        click.echo(f"Denied domains (last {since}) for sandbox '{name}':\n")
        for key in sorted(denied):
            click.echo(f"  {key}  ({denied[key]}x)")

    if do_apply:
        endpoints = [{"host": k.rsplit(":", 1)[0], "port": int(k.rsplit(":", 1)[1])} for k in denied]
        click.echo(f"\nApplying {len(endpoints)} denied domain(s)...")
        rc = _apply_endpoints(name, endpoints)
        if rc != 0:
            sys.exit(rc)
        config_dir = _kosh_config_dir()
        metadata = _read_metadata(config_dir)
        sb = metadata["sandboxes"].setdefault(name, {})
        existing = sb.setdefault("allowed_domains", [])
        for ep in endpoints:
            if ep not in existing:
                existing.append(ep)
        _write_metadata(config_dir, metadata)
        click.echo("Done — denied domains are now allowed and saved.")


# --- kosh allow profile ---


@allow.group(context_settings=CONTEXT_SETTINGS)
def profile() -> None:
    """Manage reusable domain profiles."""


@profile.command("list")
def profile_list() -> None:
    """List available profiles.

    Examples:

    \b
        kosh allow profile list
    """
    config_dir = _kosh_config_dir()
    all_profiles = _read_profiles(config_dir)
    name_w = max((len(n) for n in all_profiles), default=4)
    name_w = max(name_w, 4)
    click.echo(f"{'NAME':<{name_w}}  {'TYPE':<9}  {'DOMAINS':>7}  DESCRIPTION")
    for pname in sorted(all_profiles):
        p = all_profiles[pname]
        ptype = "built-in" if p.get("builtin") else "user"
        count = len(p.get("endpoints", []))
        desc = p.get("description", "")
        click.echo(f"{pname:<{name_w}}  {ptype:<9}  {count:>7}  {desc}")


@profile.command("show")
@click.argument("name")
def profile_show(name: str) -> None:
    """Show endpoints in a profile."""
    config_dir = _kosh_config_dir()
    all_profiles = _read_profiles(config_dir)
    p = all_profiles.get(name)
    if not p:
        click.echo(f"error: profile '{name}' not found.", err=True)
        sys.exit(1)
    ptype = "built-in" if p.get("builtin") else "user"
    click.echo(f"Profile: {name} ({ptype})")
    click.echo(f"Description: {p.get('description', '-')}")
    click.echo("Endpoints:")
    for ep in p.get("endpoints", []):
        click.echo(f"  {ep['host']}:{ep.get('port', 443)}")


@profile.command("apply")
@click.argument("name")
@click.option("--sandbox", "-s", default=None, help="Sandbox name (defaults to last used).")
def profile_apply(name: str, sandbox: str | None) -> None:
    """Apply a profile's domains to a running sandbox.

    Examples:

    \b
        kosh allow profile apply dev-tools --sandbox test
        kosh allow profile apply web-search
    """
    config_dir = _kosh_config_dir()
    all_profiles = _read_profiles(config_dir)
    p = all_profiles.get(name)
    if not p:
        click.echo(f"error: profile '{name}' not found. Use 'kosh allow profile list'.", err=True)
        sys.exit(1)
    sb_name = _resolve_sandbox_name(sandbox)
    endpoints = p.get("endpoints", [])
    binaries = p.get("binaries", DEFAULT_BINARIES)
    click.echo(f"Applying profile '{name}' ({len(endpoints)} endpoints) to '{sb_name}'...")
    rc = _apply_endpoints(sb_name, endpoints, binaries=binaries)
    if rc != 0:
        sys.exit(rc)
    metadata = _read_metadata(config_dir)
    sb = metadata["sandboxes"].setdefault(sb_name, {})
    applied = sb.setdefault("applied_profiles", [])
    if name not in applied:
        applied.append(name)
    _write_metadata(config_dir, metadata)
    click.echo("Done.")


@profile.command("create")
@click.argument("name")
@click.option("--domain", "-d", multiple=True, required=True, help="Domain (host or host:port).")
@click.option("--description", default="", help="Profile description.")
def profile_create(name: str, domain: tuple[str, ...], description: str) -> None:
    """Create a user-defined profile.

    Examples:

    \b
        kosh allow profile create my-apis -d api.corp.com -d ml.corp.com:8443
    """
    if name in BUILTIN_PROFILES:
        click.echo(f"error: '{name}' is a built-in profile and cannot be overwritten.", err=True)
        sys.exit(1)
    endpoints = []
    for d in domain:
        if ":" in d and not d.startswith("*"):
            parts = d.rsplit(":", 1)
            endpoints.append({"host": parts[0], "port": int(parts[1])})
        else:
            endpoints.append({"host": d, "port": 443})
    config_dir = _kosh_config_dir()
    pfile = config_dir / "profiles.json"
    user_profiles: dict[str, dict] = {}
    if pfile.exists():
        user_profiles = json.loads(pfile.read_text()).get("profiles", {})
    user_profiles[name] = {"description": description, "endpoints": endpoints, "binaries": DEFAULT_BINARIES}
    _write_profiles(config_dir, user_profiles)
    click.echo(f"Created profile '{name}' with {len(endpoints)} endpoint(s).")


@profile.command("delete")
@click.argument("name")
def profile_delete(name: str) -> None:
    """Delete a user-defined profile."""
    if name in BUILTIN_PROFILES:
        click.echo(f"error: cannot delete built-in profile '{name}'.", err=True)
        sys.exit(1)
    config_dir = _kosh_config_dir()
    pfile = config_dir / "profiles.json"
    if not pfile.exists():
        click.echo(f"error: profile '{name}' not found.", err=True)
        sys.exit(1)
    user_profiles = json.loads(pfile.read_text()).get("profiles", {})
    if name not in user_profiles:
        click.echo(f"error: profile '{name}' not found.", err=True)
        sys.exit(1)
    del user_profiles[name]
    _write_profiles(config_dir, user_profiles)
    click.echo(f"Deleted profile '{name}'.")


# ---------------------------------------------------------------------------
# kosh local-sandbox
# ---------------------------------------------------------------------------


class OrderedGroup(click.Group):
    """Click group that preserves command registration order."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@cli.group("local-sandbox", cls=OrderedGroup, context_settings=CONTEXT_SETTINGS)
def local_sandbox() -> None:
    """Manage local sandboxed environments.

\b
EXAMPLES
  $ kosh local-sandbox create my-project
  $ kosh local-sandbox connect my-project
  $ kosh local-sandbox list
  $ kosh local-sandbox delete my-project"""



@local_sandbox.command()
@click.argument("name", default=None, required=False)
@click.option("--name", "name_opt", default=None, hidden=True, help="[Deprecated] Use positional argument instead.")
@click.option("--model", default=DEFAULT_MODEL, show_default=True, help="Claude model to set as ANTHROPIC_MODEL.")
def create(name: str | None, name_opt: str | None, model: str) -> None:
    """Create a sandbox."""
    _check_not_in_sandbox("local-sandbox create")
    name = name or name_opt
    if not name:
        click.echo("error: sandbox name is required.", err=True)
        click.echo("Usage: kosh local-sandbox create NAME", err=True)
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        click.echo("error: ANTHROPIC_AUTH_TOKEN is not set.", err=True)
        click.echo("Export it before running this command:", err=True)
        click.echo("  export ANTHROPIC_AUTH_TOKEN=<your-token>", err=True)
        sys.exit(1)

    sandbox_dir = (pathlib.Path.cwd() / name).resolve()

    if not sandbox_dir.exists():
        click.echo(f"Creating directory {sandbox_dir}")
        sandbox_dir.mkdir(parents=True)
    else:
        click.echo(f"Directory {sandbox_dir} already exists.")

    common_lines = [
        'export PATH="$HOME/.local/bin:$PATH"',
        "alias kosh='echo \"kosh is not available inside the sandbox. To run kosh commands, exit the sandbox (type exit) or use another terminal.\"'",
        'export ANTHROPIC_BASE_URL="https://ete-litellm.ai-models.vpc-int.res.ibm.com"',
        "export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1",
        f'export ANTHROPIC_MODEL="{model}"',
    ]
    bash_ps1 = f'export PS1="\\[\\033[36m\\][kosh:{name}]\\[\\033[0m\\] \\w\\$ "'
    zsh_ps1 = f"export PS1='%F{{cyan}}[kosh:{name}]%f %~%# '"

    rc_configs = {
        ".bashrc": common_lines + [bash_ps1],
        ".zshrc": common_lines + [zsh_ps1],
    }
    for rc_name, rc_lines in rc_configs.items():
        rc_content = "\n".join(rc_lines) + "\n"
        rc_path = sandbox_dir / rc_name
        if not rc_path.exists():
            rc_path.write_text(rc_content)
            click.echo(f"Created {rc_path}")
        else:
            existing = rc_path.read_text()
            added = False
            for line in rc_lines:
                key = line.split("=")[0]
                if key not in existing:
                    with rc_path.open("a") as f:
                        f.write(line + "\n")
                    added = True
                elif "ANTHROPIC_MODEL" in key and f'"{model}"' not in existing:
                    new_text = "\n".join(
                        (line if l.startswith("export ANTHROPIC_MODEL=") else l)
                        for l in existing.splitlines()
                    ) + "\n"
                    rc_path.write_text(new_text)
                    added = True
                elif "PS1" in key and line not in existing:
                    new_text = "\n".join(
                        (line if l.strip().startswith("export PS1=") else l)
                        for l in existing.splitlines()
                    ) + "\n"
                    rc_path.write_text(new_text)
                    added = True
            if added:
                click.echo(f"Updated {rc_path}")
            else:
                click.echo(f"{rc_path} already configured.")

    config_dir = _kosh_config_dir()

    metadata = _read_metadata(config_dir)
    if name not in metadata["sandboxes"]:
        metadata["sandboxes"][name] = {"directory": str(sandbox_dir)}
        _write_metadata(config_dir, metadata)
        click.echo(f"Registered sandbox '{name}' in {config_dir / 'metadata.json'}")
    else:
        click.echo(f"Sandbox '{name}' already registered.")

    _save_last_sandbox(config_dir, sandbox_dir)
    click.echo(f"Saved as last sandbox in {config_dir / 'last_local_sandbox'}")

    _run_sandbox_sh(sandbox_dir)


@local_sandbox.command()
@click.argument("name", default=None, required=False)
@click.option("--name", "name_opt", default=None, hidden=True, help="[Deprecated] Use positional argument instead.")
def connect(name: str | None, name_opt: str | None) -> None:
    """Connect to a sandbox."""
    _check_not_in_sandbox("local-sandbox connect")
    name = name or name_opt
    config_dir = _kosh_config_dir()

    if name:
        metadata = _read_metadata(config_dir)
        entry = metadata.get("sandboxes", {}).get(name)
        if entry:
            sandbox_dir = pathlib.Path(entry["directory"])
        else:
            sandbox_base = pathlib.Path(os.environ.get("SANDBOX_DIR", pathlib.Path.home() / "sandbox"))
            sandbox_dir = (sandbox_base / name).resolve()
    else:
        last = _load_last_sandbox(config_dir)
        if not last:
            click.echo("error: no last sandbox found. Use --name or create one first.", err=True)
            sys.exit(1)
        sandbox_dir = pathlib.Path(last)

    if not sandbox_dir.is_dir():
        click.echo(f"error: sandbox directory does not exist: {sandbox_dir}", err=True)
        sys.exit(1)

    _save_last_sandbox(config_dir, sandbox_dir)
    click.echo(f"Connecting to local sandbox at {sandbox_dir}")

    _run_sandbox_sh(sandbox_dir)


@local_sandbox.command("list")
def list_sandboxes() -> None:
    """List sandboxes."""
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    sandboxes = metadata.get("sandboxes", {})
    last = _load_last_sandbox(config_dir)

    if not sandboxes:
        click.echo("No local sandboxes registered.")
        return

    name_w = max(len(n) for n in sandboxes)
    name_w = max(name_w, 4)
    click.echo(f"{'NAME':<{name_w}}  {'STATUS':<9}  DIRECTORY")
    for name, entry in sorted(sandboxes.items()):
        directory = entry.get("directory", "")
        exists = pathlib.Path(directory).is_dir()
        status = "exists" if exists else "missing"
        marker = " *" if last and pathlib.Path(last) == pathlib.Path(directory) else ""
        click.echo(f"{name:<{name_w}}  {status:<9}  {directory}{marker}")

    if last:
        click.echo(f"\n* = last used")


@local_sandbox.command()
@click.argument("name", default=None, required=False)
@click.option("--name", "name_opt", default=None, hidden=True, help="[Deprecated] Use positional argument instead.")
def delete(name: str | None, name_opt: str | None) -> None:
    """Delete a sandbox by name."""
    name = name or name_opt
    if not name:
        click.echo("error: sandbox name is required.", err=True)
        click.echo("Usage: kosh local-sandbox delete NAME", err=True)
        sys.exit(1)
    config_dir = _kosh_config_dir()
    metadata = _read_metadata(config_dir)
    entry = metadata.get("sandboxes", {}).get(name)

    if entry:
        sandbox_dir = pathlib.Path(entry["directory"])
    else:
        sandbox_base = pathlib.Path(os.environ.get("SANDBOX_DIR", pathlib.Path.home() / "sandbox"))
        sandbox_dir = (sandbox_base / name).resolve()

    if sandbox_dir.is_dir():
        click.confirm(f"Delete directory {sandbox_dir} and all its contents?", abort=True)
        import shutil as _shutil
        _shutil.rmtree(sandbox_dir)
        click.echo(f"Deleted {sandbox_dir}")
    else:
        click.echo(f"Directory {sandbox_dir} does not exist (skipping).")

    if name in metadata.get("sandboxes", {}):
        del metadata["sandboxes"][name]
        _write_metadata(config_dir, metadata)
        click.echo(f"Removed '{name}' from {config_dir / 'metadata.json'}")

    last = _load_last_sandbox(config_dir)
    if last and pathlib.Path(last) == sandbox_dir:
        (config_dir / "last_local_sandbox").unlink(missing_ok=True)
        click.echo("Cleared last_local_sandbox (was pointing to deleted sandbox).")

    click.echo(f"Sandbox '{name}' deleted.")


# --- sync-openshell ---


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _detect_gateway_version(openshell_bin: str, gateway: str | None, namespace: str) -> str | None:
    """Query the connected gateway for its version. Falls back to kubectl."""
    cmd = [openshell_bin, "status"]
    if gateway:
        cmd.extend(["-g", gateway])
    result = subprocess.run(cmd, capture_output=True, text=True)
    combined = result.stdout + result.stderr
    for line in combined.splitlines():
        clean = _ANSI_RE.sub("", line).strip()
        if clean.startswith("Version:"):
            ver = clean.split(":", 1)[1].strip()
            if ver and ver != "0.0.0":
                return ver

    kubectl = shutil.which("kubectl")
    if not kubectl:
        return None
    jsonpath = "{.spec.template.spec.containers[0].image}"
    result = subprocess.run(
        [kubectl, "get", "statefulset", "openshell-server", "-n", namespace, "-o", f"jsonpath={jsonpath}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    tag = result.stdout.strip().rsplit(":", 1)[-1]
    tag = tag.lstrip("v")
    tag = re.sub(r"-kagenti\.\d+$", "", tag)
    if re.match(r"^\d+\.\d+\.\d+", tag):
        return tag
    return None


def _update_script_dependency(version: str | None) -> tuple[str, str]:
    """Rewrite kosh.py inline metadata to pin/unpin openshell. Returns (old, new) dep strings."""
    script_path = pathlib.Path(__file__).resolve()
    content = script_path.read_text()

    if version:
        new_dep = f'"openshell=={version}"'
        new_shebang_with = f"--with openshell=={version}"
    else:
        new_dep = '"openshell"'
        new_shebang_with = "--with openshell"

    header = content[:content.find("# ///", content.find("# ///") + 1) + 5]
    old_dep_match = re.search(r'"openshell[^"]*"', header)
    old_dep = old_dep_match.group(0) if old_dep_match else '"openshell"'

    new_content = re.sub(
        r'(#\s+"openshell)[^"]*(")',
        lambda m: f'{m.group(1)}=={version}{m.group(2)}' if version else f'{m.group(1)}{m.group(2)}',
        content,
        count=1,
    )
    new_content = re.sub(
        r"--with openshell[^\s]*",
        new_shebang_with,
        new_content,
        count=1,
    )
    script_path.write_text(new_content)
    return old_dep, new_dep


def _sync_cli_binary(version: str) -> bool:
    """Install a specific openshell CLI version via uv tool. Returns success."""
    uv = shutil.which("uv")
    if not uv:
        click.echo("error: 'uv' not found in PATH.", err=True)
        return False
    result = subprocess.run(
        [uv, "tool", "install", "--force", f"openshell=={version}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo(f"error: uv tool install failed:\n{result.stderr.strip()}", err=True)
        return False
    return True


@cli.command("sync-openshell")
@click.option("--gateway", "-g", default=None, help="Gateway name (passed to openshell status -g).")
@click.option("--version", "target_version", default=None, help="Explicit target version (skip gateway query).")
@click.option("--dry-run", is_flag=True, help="Show what would change without modifying anything.")
@click.option("--unpin", is_flag=True, help="Remove version pin (revert to unpinned 'openshell').")
@click.option("--skip-cli", is_flag=True, help="Only update the script dependency, skip CLI binary.")
@click.option("--skip-script", is_flag=True, help="Only update CLI binary, skip script dependency.")
@click.option("--namespace", "-n", default="openshell", help="K8s namespace for kubectl fallback.")
def sync_openshell(gateway: str | None, target_version: str | None, dry_run: bool, unpin: bool, skip_cli: bool, skip_script: bool, namespace: str) -> None:
    """Sync local openshell tooling to match the remote gateway version.

    Detects the version from the connected gateway (via openshell status),
    then pins the kosh.py inline uv dependency and installs the matching
    CLI binary.

    Examples:

    \b
        kosh sync-openshell -g kind-kagenti
        kosh sync-openshell --version 0.0.41
        kosh sync-openshell --dry-run
        kosh sync-openshell --unpin
    """
    openshell_bin = _find_openshell()

    if unpin:
        if dry_run:
            click.echo("[dry-run] Would remove version pin from kosh.py dependency.")
            return
        old_dep, new_dep = _update_script_dependency(None)
        click.echo(f"Script dependency: {old_dep} -> {new_dep}")
        click.echo("Unpinned. Run 'uv tool install -U openshell' to get latest CLI.")
        return

    if not target_version:
        click.echo(f"Detecting gateway version...")
        target_version = _detect_gateway_version(openshell_bin, gateway, namespace)
        if not target_version:
            click.echo("error: could not detect gateway version.", err=True)
            click.echo("Use --version to specify explicitly, or check gateway connectivity.", err=True)
            sys.exit(1)

    click.echo(f"Target version: {target_version}")

    cli_result = subprocess.run([openshell_bin, "--version"], capture_output=True, text=True)
    current_cli = cli_result.stdout.strip().split()[-1] if cli_result.returncode == 0 else "unknown"
    click.echo(f"Current CLI version: {current_cli}")

    script_path = pathlib.Path(__file__).resolve()
    content = script_path.read_text()
    header = content[:content.find("# ///", content.find("# ///") + 1) + 5]
    dep_match = re.search(r'"openshell([^"]*)"', header)
    current_script_dep = f'"openshell{dep_match.group(1)}"' if dep_match else '"openshell"'
    click.echo(f"Current script dependency: {current_script_dep}")

    if dry_run:
        click.echo(f"\n[dry-run] Would pin script dependency to: \"openshell=={target_version}\"")
        click.echo(f"[dry-run] Would install CLI: openshell=={target_version}")
        return

    if not skip_script:
        old_dep, new_dep = _update_script_dependency(target_version)
        click.echo(f"\nScript dependency: {old_dep} -> {new_dep}")

    if not skip_cli:
        click.echo(f"Installing CLI openshell=={target_version}...")
        if _sync_cli_binary(target_version):
            verify = subprocess.run([openshell_bin, "--version"], capture_output=True, text=True)
            new_ver = verify.stdout.strip() if verify.returncode == 0 else "unknown"
            click.echo(f"CLI: {current_cli} -> {new_ver}")
        else:
            sys.exit(1)

    click.echo("\nSync complete.")


# ---------------------------------------------------------------------------
# Kagenti API commands (deploy agents/tools without kubectl)
# ---------------------------------------------------------------------------

import ssl
import time
import urllib.request
import urllib.parse
import urllib.error

DEFAULT_KAGENTI_URL = os.environ.get(
    "KAGENTI_URL",
    "https://kagenti-backend-kagenti-system.apps.epoc002.ete14.res.ibm.com",
)

DEFAULT_KAGENTI_KEYCLOAK_URL = os.environ.get(
    "KAGENTI_KEYCLOAK_URL",
    "https://keycloak-keycloak.apps.epoc002.ete14.res.ibm.com",
)

DEFAULT_KAGENTI_REALM = "kagenti"
DEFAULT_KAGENTI_CLIENT_ID = "admin-cli"


def _kagenti_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _kagenti_token_file() -> pathlib.Path:
    return _kosh_config_dir() / "kagenti_token.json"


def _save_kagenti_token(token_data: dict) -> None:
    token_file = _kagenti_token_file()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps(token_data, indent=2) + "\n")
    token_file.chmod(0o600)


def _load_kagenti_token() -> dict | None:
    token_file = _kagenti_token_file()
    if not token_file.exists():
        return None
    try:
        data = json.loads(token_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("expires_at", 0) < time.time():
        return None
    return data


def _kagenti_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make authenticated request to Kagenti API."""
    token_data = _load_kagenti_token()
    if token_data is None:
        click.echo("error: Not logged in. Run: kosh login", err=True)
        sys.exit(1)

    url = f"{token_data['kagenti_url']}{path}"
    headers = {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Content-Type": "application/json",
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, context=_kagenti_ssl_ctx(), timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            detail = json.loads(error_body).get("detail", error_body)
        except json.JSONDecodeError:
            detail = error_body
        click.echo(f"error: HTTP {e.code} — {detail}", err=True)
        sys.exit(1)
    except (urllib.error.URLError, OSError) as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


def _parse_env_vars(env_list: tuple[str, ...]) -> list[dict]:
    """Parse --env KEY=VALUE pairs into API format."""
    result = []
    for item in env_list:
        if "=" not in item:
            click.echo(f"error: Invalid env format '{item}', expected KEY=VALUE", err=True)
            sys.exit(1)
        key, value = item.split("=", 1)
        result.append({"name": key, "value": value})
    return result


# --- kosh login ---

@cli.command("login")
@click.option("--kagenti-url", default=DEFAULT_KAGENTI_URL, show_default=True,
              help="Kagenti backend URL")
@click.option("--keycloak-url", default=DEFAULT_KAGENTI_KEYCLOAK_URL, show_default=True,
              help="Keycloak URL")
@click.option("--user", "-u", required=True, help="Username")
@click.option("--password", "-p", required=True, help="Password")
@click.option("--realm", default=DEFAULT_KAGENTI_REALM, show_default=True)
@click.option("--client-id", default=DEFAULT_KAGENTI_CLIENT_ID, show_default=True)
def kagenti_login(kagenti_url, keycloak_url, user, password, realm, client_id):
    """Authenticate with Kagenti (Keycloak password grant)."""
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    form_data = urllib.parse.urlencode({
        "grant_type": "password",
        "client_id": client_id,
        "username": user,
        "password": password,
        "scope": "openid",
    }).encode()

    req = urllib.request.Request(token_url, data=form_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, context=_kagenti_ssl_ctx(), timeout=15) as resp:
            token_resp = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        click.echo(f"error: Login failed (HTTP {e.code}): {error_body}", err=True)
        sys.exit(1)
    except (urllib.error.URLError, OSError) as e:
        click.echo(f"error: Cannot reach Keycloak: {e}", err=True)
        sys.exit(1)

    expires_in = token_resp.get("expires_in", 300)
    token_data = {
        "access_token": token_resp["access_token"],
        "refresh_token": token_resp.get("refresh_token", ""),
        "expires_at": time.time() + expires_in,
        "kagenti_url": kagenti_url.rstrip("/"),
        "keycloak_url": keycloak_url.rstrip("/"),
        "realm": realm,
        "client_id": client_id,
    }
    _save_kagenti_token(token_data)
    click.echo(f"Logged in as {user} (token expires in {expires_in}s)")
    click.echo(f"  Kagenti: {kagenti_url}")
    click.echo(f"  Token: {_kagenti_token_file()}")


# --- kosh deploy ---

@cli.group("deploy", context_settings=CONTEXT_SETTINGS)
def deploy():
    """Deploy agents and tools via Kagenti API (no kubectl needed)."""


@deploy.command("agent")
@click.option("--name", required=True, help="Agent name")
@click.option("--namespace", "-n", default="team1", show_default=True)
@click.option("--image", required=True, help="Container image URL")
@click.option("--protocol", default="a2a", show_default=True,
              type=click.Choice(["a2a", "mcp", "streamable_http"]))
@click.option("--framework", default="LangGraph", show_default=True)
@click.option("--port", default=8080, type=int, show_default=True, help="Service port")
@click.option("--target-port", default=8000, type=int, show_default=True, help="Container port")
@click.option("--authbridge/--no-authbridge", default=True, show_default=True)
@click.option("--spire/--no-spire", default=False, show_default=True)
@click.option("--env", "-e", multiple=True, help="Environment variable (KEY=VALUE)")
def deploy_agent(name, namespace, image, protocol, framework, port, target_port,
                 authbridge, spire, env):
    """Deploy an agent from a container image."""
    body = {
        "name": name,
        "namespace": namespace,
        "deploymentMethod": "image",
        "containerImage": image,
        "protocol": protocol,
        "framework": framework,
        "workloadType": "deployment",
        "authBridgeEnabled": authbridge,
        "spireEnabled": spire,
        "servicePorts": [
            {"name": "http", "port": port, "targetPort": target_port, "protocol": "TCP"}
        ],
    }
    if env:
        body["envVars"] = _parse_env_vars(env)

    click.echo(f"Deploying agent '{name}' in {namespace} from {image}...")
    result = _kagenti_request("POST", "/api/v1/agents", body)
    if result.get("success"):
        click.echo(f"  OK: {result.get('message', 'Agent created')}")
    else:
        click.echo(f"  Failed: {result.get('message', 'Unknown error')}", err=True)
        sys.exit(1)


@deploy.command("tool")
@click.option("--name", required=True, help="Tool name")
@click.option("--namespace", "-n", default="team1", show_default=True)
@click.option("--image", required=True, help="Container image URL")
@click.option("--protocol", default="streamable_http", show_default=True,
              type=click.Choice(["streamable_http", "sse", "stdio"]))
@click.option("--framework", default="Python", show_default=True)
@click.option("--port", default=8000, type=int, show_default=True, help="Service port")
@click.option("--target-port", default=8000, type=int, show_default=True, help="Container port")
@click.option("--env", "-e", multiple=True, help="Environment variable (KEY=VALUE)")
def deploy_tool(name, namespace, image, protocol, framework, port, target_port, env):
    """Deploy a tool (MCP server) from a container image."""
    body = {
        "name": name,
        "namespace": namespace,
        "deploymentMethod": "image",
        "containerImage": image,
        "protocol": protocol,
        "framework": framework,
        "workloadType": "deployment",
        "authBridgeEnabled": False,
        "servicePorts": [
            {"name": "http", "port": port, "targetPort": target_port, "protocol": "TCP"}
        ],
    }
    if env:
        body["envVars"] = _parse_env_vars(env)

    click.echo(f"Deploying tool '{name}' in {namespace} from {image}...")
    result = _kagenti_request("POST", "/api/v1/tools", body)
    if result.get("success"):
        click.echo(f"  OK: {result.get('message', 'Tool created')}")
    else:
        click.echo(f"  Failed: {result.get('message', 'Unknown error')}", err=True)
        sys.exit(1)


# --- kosh catalog ---

@cli.group("catalog", context_settings=CONTEXT_SETTINGS)
def catalog():
    """List agents and tools from Kagenti API."""


@catalog.command("agents")
@click.option("--namespace", "-n", default="team1", show_default=True)
def catalog_agents(namespace):
    """List deployed agents."""
    result = _kagenti_request("GET", f"/api/v1/agents?namespace={namespace}")
    agents = result if isinstance(result, list) else result.get("agents", result.get("items", []))
    if not agents:
        click.echo(f"No agents in namespace '{namespace}'.")
        return
    click.echo(f"{'NAME':<25} {'PROTOCOL':<12} {'FRAMEWORK':<12} {'IMAGE'}")
    click.echo(f"{'-'*25} {'-'*12} {'-'*12} {'-'*40}")
    for a in agents:
        name = a.get("name", "?")
        proto = a.get("protocol", "?")
        fw = a.get("framework", "?")
        img = a.get("containerImage", a.get("image", "—"))
        click.echo(f"{name:<25} {proto:<12} {fw:<12} {img}")


@catalog.command("tools")
@click.option("--namespace", "-n", default="team1", show_default=True)
def catalog_tools(namespace):
    """List deployed tools."""
    result = _kagenti_request("GET", f"/api/v1/tools?namespace={namespace}")
    tools = result if isinstance(result, list) else result.get("tools", result.get("items", []))
    if not tools:
        click.echo(f"No tools in namespace '{namespace}'.")
        return
    click.echo(f"{'NAME':<25} {'PROTOCOL':<16} {'FRAMEWORK':<12} {'IMAGE'}")
    click.echo(f"{'-'*25} {'-'*16} {'-'*12} {'-'*40}")
    for t in tools:
        name = t.get("name", "?")
        proto = t.get("protocol", "?")
        fw = t.get("framework", "?")
        img = t.get("containerImage", t.get("image", "—"))
        click.echo(f"{name:<25} {proto:<16} {fw:<12} {img}")


# --- kosh undeploy ---

@cli.group("undeploy", context_settings=CONTEXT_SETTINGS)
def undeploy():
    """Remove deployed agents/tools via Kagenti API."""


@undeploy.command("agent")
@click.option("--name", required=True, help="Agent name")
@click.option("--namespace", "-n", default="team1", show_default=True)
@click.confirmation_option(prompt="Delete this agent?")
def undeploy_agent(name, namespace):
    """Delete a deployed agent."""
    click.echo(f"Deleting agent '{name}' from {namespace}...")
    result = _kagenti_request("DELETE", f"/api/v1/agents/{namespace}/{name}")
    msg = result.get("message", "Agent deleted") if isinstance(result, dict) else "Agent deleted"
    click.echo(f"  OK: {msg}")


@undeploy.command("tool")
@click.option("--name", required=True, help="Tool name")
@click.option("--namespace", "-n", default="team1", show_default=True)
@click.confirmation_option(prompt="Delete this tool?")
def undeploy_tool(name, namespace):
    """Delete a deployed tool."""
    click.echo(f"Deleting tool '{name}' from {namespace}...")
    result = _kagenti_request("DELETE", f"/api/v1/tools/{namespace}/{name}")
    msg = result.get("message", "Tool deleted") if isinstance(result, dict) else "Tool deleted"
    click.echo(f"  OK: {msg}")


if __name__ == "__main__":
    cli(prog_name="kosh")
