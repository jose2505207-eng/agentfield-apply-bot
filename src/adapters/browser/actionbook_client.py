"""
Actionbook CLI wrapper — async Python adapter.

Actionbook ships its primary interface as a Rust CLI that connects to a real
Chrome (via a browser extension + Chrome DevTools Protocol) and exposes
commands for snapshots, clicks, fills, screenshots, etc.

This module is the boundary between our async Python pipeline and that CLI.
Every public method shells out via asyncio.create_subprocess_exec, captures
stdout, and (where applicable) parses it.

WHY SUBPROCESS AND NOT AN HTTP/SDK CLIENT:
  Actionbook commits to the CLI as the stable contract. They also ship a JS
  SDK and an MCP server, but no first-party Python SDK and no documented HTTP
  port that's guaranteed across versions. Subprocess to the CLI is the
  cheapest reliable contract for us.

CHROME PROFILE REQUIREMENT:
  The CLI drives whatever browser Actionbook's extension is attached to.
  Pre-authentication is done by the USER (manually logging in to Wellfound,
  Indeed, LinkedIn, etc.) in a dedicated Chrome profile. The bot inherits
  those cookies. See README for the profile setup steps.

ERROR MODEL:
  Each method raises ActionbookError on non-zero exit / timeout. The caller
  (apply_to_job) catches and converts to a stuck ApplyResult — never crashes
  the whole pipeline because of one site misbehaving.

KNOWN UNCERTAINTY (read me before depending on every method):
  The exact command surface of Actionbook is documented but moving. The CLI
  flags below match what the public docs and the GitHub README show as of
  early May 2026. If a command signature changes (e.g. `upload` is renamed
  to `set_files`), this is the ONE file to update. Methods marked
  # VERIFY: are the ones I'm least confident about.
"""
from __future__ import annotations
import asyncio
import json
import shlex
from pathlib import Path
from typing import Optional


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


class ActionbookClient:
    """Async wrapper around the `actionbook` CLI binary.

    Usage:
        ab = ActionbookClient()
        session = await ab.start_session()
        await ab.open("https://example.com/apply", session=session)
        snap = await ab.snapshot(session=session)
        # ... LLM picks @e5 ...
        await ab.click("@e5", session=session)
    """

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
    # Health / diagnostics
    # ------------------------------------------------------------------

    async def status(self) -> str:
        """Return raw output of `actionbook browser status`. Useful for diagnostics."""
        return await self._run(["browser", "status"])

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def start_session(self) -> str:
        """Start a browser session. Return its session id.

        Actionbook's stdout may be JSON or a plain id depending on version;
        we try JSON first and fall back to first non-empty line.
        """
        out = await self._run(["browser", "start"])
        try:
            data = json.loads(out)
            sid = data.get("session_id") or data.get("session") or data.get("id")
            if sid:
                return str(sid)
        except json.JSONDecodeError:
            pass
        for line in out.splitlines():
            line = line.strip()
            if line:
                return line
        raise ActionbookError(
            cmd="actionbook browser start",
            returncode=0,
            stderr="started OK but stdout had no parseable session id",
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def open(self, url: str, *, session: str) -> None:
        """Open `url` in a NEW tab of the session."""
        await self._run(["browser", "open", url, "--session", session])

    async def goto(self, url: str, *, session: str) -> None:
        """Navigate the session's active tab to `url` (no new tab)."""
        await self._run(["browser", "goto", url, "--session", session])

    # ------------------------------------------------------------------
    # Snapshot — the LLM's eye into the page
    # ------------------------------------------------------------------

    async def snapshot(self, *, session: str) -> str:
        """Return the accessibility snapshot as text. Includes refs (@e1, @e2, ...)."""
        # snapshots can be big; allow longer timeout
        return await self._run(["browser", "snapshot", "--session", session], timeout=60.0)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def click(self, ref: str, *, session: str) -> None:
        """Click the element identified by `ref` (e.g. '@e5')."""
        await self._run(["browser", "click", ref, "--session", session])

    async def fill(self, ref: str, value: str, *, session: str) -> None:
        """Type `value` into the input identified by `ref`."""
        await self._run(["browser", "fill", ref, value, "--session", session])

    async def select(self, ref: str, value: str, *, session: str) -> None:  # VERIFY: command name
        """Choose `value` (label or value attr) on the <select> at `ref`.

        VERIFY before depending on this in demo: the docs I saw show 'click'
        on the option after expanding the dropdown; some versions expose
        a `select` command directly. If this raises, fall back to:
            await self.click(ref); await self.click(option_ref)
        """
        await self._run(["browser", "select", ref, value, "--session", session])

    async def upload(self, ref: str, path: str, *, session: str) -> None:  # VERIFY: command name
        """Attach file at absolute `path` to the file input at `ref`.

        VERIFY before demo: Actionbook's file-input handling may be called
        'upload', 'set_files', or 'attach' depending on version. Adjust the
        command name here if the first test against a real Greenhouse/Lever
        file input fails.
        """
        abs_path = str(Path(path).expanduser().resolve())
        if not Path(abs_path).is_file():
            raise ActionbookError(
                cmd=f"upload {ref} {path}",
                returncode=-1,
                stderr=f"file does not exist: {abs_path}",
            )
        await self._run(["browser", "upload", ref, abs_path, "--session", session])

    async def screenshot(self, output_path: str, *, session: str) -> str:
        """Save a PNG screenshot to `output_path`. Return the absolute path saved."""
        abs_path = str(Path(output_path).expanduser().resolve())
        Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
        await self._run(
            ["browser", "screenshot", abs_path, "--session", session],
        )
        return abs_path

    async def eval_js(self, expression: str, *, session: str) -> str:
        """Evaluate a JS expression and return its stringified result."""
        return await self._run(
            ["browser", "eval", expression, "--session", session]
        )

    async def current_url(self, *, session: str) -> str:
        """Return the URL of the session's active tab."""
        out = await self.eval_js("window.location.href", session=session)
        return out.strip().strip('"').strip("'")

    async def wait(self, seconds: float) -> None:
        """Pure Python sleep — no CLI call. Provided as a uniform action."""
        await asyncio.sleep(seconds)
