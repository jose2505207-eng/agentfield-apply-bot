"""
Actionbook CLI wrapper — async Python adapter (v0.4.2-validated).

This module is the boundary between our async Python pipeline and the Rust
CLI Actionbook ships at `actionbook`. Every public method shells out via
asyncio.create_subprocess_exec, captures stdout, and (where applicable)
parses it.

WHY SUBPROCESS AND NOT AN HTTP/SDK CLIENT:
  Actionbook commits to the CLI as the stable contract. No first-party
  Python SDK and no documented HTTP port. Subprocess to the CLI is the
  cheapest reliable contract.

CHROME PROFILE REQUIREMENT:
  Pre-authentication is done by the USER (manually logging in to
  Wellfound, Indeed, LinkedIn, etc.) in a Chrome profile where the
  Actionbook extension is installed and connected to the daemon's bridge.
  The bot inherits those cookies.

ERROR MODEL:
  Each method raises ActionbookError on non-zero exit / timeout. The
  caller (apply_to_job) catches and converts to a stuck/manual_review
  ApplyResult — never crashes the whole pipeline because of one site
  misbehaving.

CHANGES FROM v0 OF THIS FILE (post-live-validation on May 12 2026):
  1. EVERY browser command requires BOTH --session AND --tab. The wrapper
     now enforces this in every method signature.
  2. `start_session` uses `--mode extension --set-session-id <id>
     --open-url <url>` and returns a BrowserSession (session_id, tab_id)
     parsed from stdout's `[s1 t1] <url>` status line. The previous
     "first non-empty line" parser was wrong — that line is the status
     prefix, not a session id.
  3. `snapshot` no longer returns stdout. Stdout is just the help text
     and a path. We extract the path, read the YAML file, and return its
     contents — which is what the LLM actually wants.
  4. Native `scroll <direction>` command exists. The old eval_js
     workaround is gone.
  5. Native `url` command replaces the eval_js trick for current_url.
  6. `extension_status` is the bridgeable diagnostic that does NOT
     require a session — useful for smoke tests before any browser
     session is started.

KNOWN-GOOD COMMAND SHAPES (cross-verified against `--help` outputs):
  actionbook browser start --mode extension --set-session-id s1 --open-url <url>
  actionbook browser snapshot --session s1 --tab t1 [-i] [-c]
  actionbook browser click @e5 --session s1 --tab t1
  actionbook browser fill @e7 "text" --session s1 --tab t1
  actionbook browser select @e3 "label" --session s1 --tab t1
  actionbook browser upload @e9 /abs/path/file.pdf --session s1 --tab t1
  actionbook browser scroll down --session s1 --tab t1
  actionbook browser screenshot /abs/path.png --session s1 --tab t1
  actionbook browser url --session s1 --tab t1
"""
from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------------
# Public types
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BrowserSession:
    """Identifier for one Actionbook browser session+tab pair.

    All browser-level commands require BOTH ids. apply_to_job receives
    a BrowserSession from start_session() and passes the parts to each
    subsequent call.
    """
    session_id: str
    tab_id: str


class ActionbookError(RuntimeError):
    """Raised when an Actionbook CLI command fails or times out."""

    def __init__(self, cmd: str, returncode: int, stderr: str):
        super().__init__(
            f"actionbook command failed (exit {returncode})\n"
            f"  cmd:    {cmd}\n"
            f"  stderr: {stderr.strip()}"
        )
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr


# ----------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------


class ActionbookClient:
    """Async wrapper around the `actionbook` CLI binary.

    Usage:
        ab = ActionbookClient()
        sess = await ab.start_session(
            session_id="agentfield",
            open_url="https://example.com/apply",
        )
        snap = await ab.snapshot(session=sess.session_id, tab=sess.tab_id)
        # ... LLM picks @e5 ...
        await ab.click("@e5", session=sess.session_id, tab=sess.tab_id)
    """

    # Regex that extracts (session_id, tab_id) from a status-prefix line
    # like "[s1 t1] https://www.google.com".
    _STATUS_LINE_RE = re.compile(r"^\[(\S+)\s+(\S+)\]")

    # Regex that extracts the snapshot YAML path from snapshot stdout.
    # Sample: "output saved to /home/.actionbook/sessions/s1/snapshot_X.yaml"
    _SNAPSHOT_PATH_RE = re.compile(r"output saved to (\S+\.ya?ml)")

    def __init__(
        self,
        binary: str = "actionbook",
        default_timeout: float = 30.0,
    ):
        self.binary = binary
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # Internal: run a CLI command and capture stdout
    # ------------------------------------------------------------------

    async def _run(
        self,
        args: list[str],
        timeout: Optional[float] = None,
    ) -> str:
        """Run `actionbook <args>` and return stdout text. Raise on non-zero exit or timeout."""
        cmd = [self.binary, *args]
        cmd_display = " ".join(shlex.quote(a) for a in cmd)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self.default_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ActionbookError(
                cmd=cmd_display,
                returncode=-1,
                stderr=f"timed out after {timeout or self.default_timeout}s",
            )

        if proc.returncode != 0:
            raise ActionbookError(
                cmd=cmd_display,
                returncode=proc.returncode or -1,
                stderr=stderr_b.decode("utf-8", errors="replace"),
            )
        return stdout_b.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Diagnostics — do not require a session
    # ------------------------------------------------------------------

    async def extension_status(self) -> str:
        """Return raw output of `actionbook extension status`.

        Useful as a pre-flight: tells you whether the bridge is listening
        and whether the Chrome extension is connected, WITHOUT needing
        a browser session to exist yet.
        """
        return await self._run(["extension", "status"])

    async def extension_ping(self) -> str:
        """Return raw output of `actionbook extension ping`."""
        return await self._run(["extension", "ping"])

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def start_session(
        self,
        *,
        session_id: str = "agentfield",
        open_url: Optional[str] = None,
        mode: str = "extension",
    ) -> BrowserSession:
        """Start (or reuse) a browser session and return its (session_id, tab_id).

        Args:
            session_id: Semantic ID to assign via --set-session-id.
                Re-uses an existing Running session with the same ID instead
                of creating a duplicate.
            open_url: URL to open on start. Required in extension mode unless
                attaching to an existing tab via tab_id (not used here).
            mode: 'extension' (default) | 'local' | 'cloud'.

        Returns:
            BrowserSession(session_id, tab_id). The tab_id is read from the
            status prefix the CLI emits, e.g. "[s1 t1] https://...".
        """
        args = ["browser", "start", "--mode", mode, "--set-session-id", session_id]
        if open_url:
            args += ["--open-url", open_url]

        out = await self._run(args, timeout=60.0)
        sess, tab = self._parse_status_prefix(out)
        if not sess or not tab:
            raise ActionbookError(
                cmd=" ".join(args),
                returncode=0,
                stderr=(
                    "could not parse [session tab] prefix from start output:\n"
                    f"{out[:500]}"
                ),
            )
        return BrowserSession(session_id=sess, tab_id=tab)

    async def list_sessions(self) -> str:
        """Raw output of `actionbook browser list-sessions`. Mostly for debugging."""
        return await self._run(["browser", "list-sessions"])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def open(self, url: str, *, session: str, tab: str) -> None:
        """Open `url` in a new tab of the session.

        NOTE: this opens an ADDITIONAL tab. To reuse the existing tab,
        use goto() instead.
        """
        await self._run(
            ["browser", "new-tab", url, "--session", session]
        )

    async def goto(self, url: str, *, session: str, tab: str) -> None:
        """Navigate the given tab to `url`."""
        await self._run(
            ["browser", "goto", url, "--session", session, "--tab", tab]
        )

    # ------------------------------------------------------------------
    # Snapshot — the LLM's eye into the page
    # ------------------------------------------------------------------

    async def snapshot(
        self,
        *,
        session: str,
        tab: str,
        interactive: bool = True,
        compact: bool = True,
    ) -> str:
        """Capture an accessibility snapshot and return its YAML contents.

        Actionbook writes the snapshot to a file under
        ~/.actionbook/sessions/<sid>/snapshot_<ts>.yaml and prints the path
        on stdout. We read that file and return its body — that is what
        the LLM consumes.

        Args:
            interactive: Pass -i to include only interactive elements.
                On forms this drastically cuts token cost while preserving
                everything the LLM needs to act.
            compact: Pass -c to remove empty structural nodes.

        Returns:
            The YAML body of the snapshot. Refs in the YAML look like
            `[ref=e5]`; commands target them as `@e5`.
        """
        args = ["browser", "snapshot", "--session", session, "--tab", tab]
        if interactive:
            args.append("-i")
        if compact:
            args.append("-c")

        # Snapshots can take a moment on heavy pages.
        out = await self._run(args, timeout=60.0)

        m = self._SNAPSHOT_PATH_RE.search(out)
        if not m:
            raise ActionbookError(
                cmd=" ".join(args),
                returncode=0,
                stderr=(
                    "could not find 'output saved to ...yaml' line in snapshot stdout:\n"
                    f"{out[:500]}"
                ),
            )
        yaml_path = Path(m.group(1))
        try:
            return yaml_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ActionbookError(
                cmd=" ".join(args),
                returncode=0,
                stderr=f"snapshot file unreadable at {yaml_path}: {e}",
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def click(self, ref: str, *, session: str, tab: str) -> None:
        """Click the element identified by `ref` (e.g. '@e5') or a CSS selector."""
        await self._run(
            ["browser", "click", ref, "--session", session, "--tab", tab]
        )

    async def fill(self, ref: str, value: str, *, session: str, tab: str) -> None:
        """Type `value` into the input identified by `ref`."""
        await self._run(
            ["browser", "fill", ref, value, "--session", session, "--tab", tab]
        )

    async def select(self, ref: str, value: str, *, session: str, tab: str) -> None:
        """Choose `value` on the <select> at `ref`. `value` is the option's label or value."""
        await self._run(
            ["browser", "select", ref, value, "--session", session, "--tab", tab]
        )

    async def upload(
        self, ref: str, path: str, *, session: str, tab: str
    ) -> None:
        """Attach file at absolute `path` to the file input at `ref`."""
        abs_path = str(Path(path).expanduser().resolve())
        if not Path(abs_path).is_file():
            raise ActionbookError(
                cmd=f"upload {ref} {path}",
                returncode=-1,
                stderr=f"file does not exist: {abs_path}",
            )
        await self._run(
            [
                "browser", "upload", ref, abs_path,
                "--session", session, "--tab", tab,
            ]
        )

    async def scroll(
        self,
        direction: str = "down",
        *,
        session: str,
        tab: str,
    ) -> None:
        """Scroll the page. `direction` is 'up' | 'down' | 'top' | 'bottom' | etc.

        Actionbook v0.4.2 exposes scroll natively, so we no longer need the
        eval_js workaround. Defaults to 'down' which is the only thing the
        LLM ever asks for during form-filling.
        """
        await self._run(
            ["browser", "scroll", direction, "--session", session, "--tab", tab]
        )

    async def screenshot(
        self, output_path: str, *, session: str, tab: str
    ) -> str:
        """Save a PNG screenshot to `output_path`. Return the absolute path saved."""
        abs_path = str(Path(output_path).expanduser().resolve())
        Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
        await self._run(
            [
                "browser", "screenshot", abs_path,
                "--session", session, "--tab", tab,
            ]
        )
        return abs_path

    async def eval_js(
        self, expression: str, *, session: str, tab: str
    ) -> str:
        """Evaluate a JS expression and return its stringified result."""
        return await self._run(
            ["browser", "eval", expression, "--session", session, "--tab", tab]
        )

    async def current_url(self, *, session: str, tab: str) -> str:
        """Return the URL of the given tab using the native `url` command."""
        out = await self._run(
            ["browser", "url", "--session", session, "--tab", tab]
        )
        # Output may be prefixed with "[s1 t1] https://...". Strip the
        # prefix if present; otherwise return the first http-looking line.
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            m = self._STATUS_LINE_RE.match(line)
            if m:
                # The URL is whatever follows the bracketed status.
                tail = line[m.end():].strip()
                if tail.startswith("http"):
                    return tail
            if line.startswith("http"):
                return line
        return out.strip()

    async def wait(self, seconds: float) -> None:
        """Pure Python sleep — no CLI call. Provided as a uniform action."""
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse_status_prefix(cls, out: str) -> tuple[Optional[str], Optional[str]]:
        """Extract (session_id, tab_id) from any line of the form `[s1 t1] ...`."""
        for line in out.splitlines():
            m = cls._STATUS_LINE_RE.match(line.strip())
            if m:
                return m.group(1), m.group(2)
        return None, None
