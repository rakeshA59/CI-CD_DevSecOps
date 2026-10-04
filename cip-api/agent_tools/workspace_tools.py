"""
Workspace Tools – the LangChain tools agents bind to (`llm.bind_tools(WorkspaceTools(...).tools)`).

They let an agent look at the checked-out repository and act on it, always inside the run's workspace:
    list_files        what is in a folder (dependency / build folders hidden)
    read_file         the start of a file (manifests, Dockerfile, README, test files …)
    run_command       a shell command in a folder of the repo (install, build, test …)
    write_file        create / overwrite a file (generated tests, Dockerfile)
    install_toolchain download a portable JDK / Maven / Gradle / Node / Go when the machine does not have it
"""

import os
from pathlib import Path

from langchain_core.tools import StructuredTool

from agent_tools import toolchain_installer
from utils.agent_events import run_command as _run

HIDDEN = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".idea", ".vscode", ".gradle"}


class WorkspaceTools:
    """Tools scoped to one workspace folder; `commands` records what was run (step evidence)."""

    def __init__(self, workspace: str, task_id: str = "", node: str = ""):
        self.root = Path(workspace).resolve()
        self.task_id, self.node = task_id, node
        self.commands: list[dict] = []
        self.extra_path: list[str] = []
        self.extra_env: dict = {}
        self.tools = [
            StructuredTool.from_function(coroutine=self.list_files, name="list_files",
                                         description="List files and folders of a repo folder (relative path, '.' = repo root)."),
            StructuredTool.from_function(coroutine=self.read_file, name="read_file",
                                         description="Read up to max_chars characters of a repo file (relative path)."),
            StructuredTool.from_function(coroutine=self.run_command, name="run_command",
                                         description="Run a shell command inside a repo folder (relative path) and get exit code + output."),
            StructuredTool.from_function(coroutine=self.write_file, name="write_file",
                                         description="Create or overwrite a file in the repo (relative path) with the given content."),
            StructuredTool.from_function(coroutine=self.install_toolchain, name="install_toolchain",
                                         description="Install a missing build tool for this run: jdk, maven, gradle, node or go "
                                                     "(version optional, e.g. '17' for jdk)."),
        ]

    def _path(self, rel: str) -> Path:
        p = (self.root / (rel or ".")).resolve()
        if self.root not in (p, *p.parents):
            raise ValueError(f"{rel} is outside the repository")
        return p

    async def list_files(self, path: str = ".", depth: int = 2) -> str:
        """Folder tree (depth levels)."""
        base, lines = self._path(path), []
        for dirpath, dirs, files in os.walk(base):
            level = len(Path(dirpath).relative_to(base).parts)
            dirs[:] = sorted(d for d in dirs if d not in HIDDEN) if level < depth else []
            lines += [str((Path(dirpath) / f).relative_to(self.root)).replace("\\", "/") for f in sorted(files)]
            if len(lines) > 400:
                break
        return "\n".join(lines[:400]) or "(empty)"

    async def read_file(self, path: str, max_chars: int = 6000) -> str:
        """Start of a file."""
        p = self._path(path)
        if not p.is_file():
            return f"{path}: not found"
        return p.read_text(encoding="utf-8", errors="replace")[:max_chars]

    async def write_file(self, path: str, content: str) -> str:
        """Create / overwrite a file."""
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} chars)"

    async def run_command(self, command: str, folder: str = ".", timeout: int = 1800) -> str:
        """Run a command; returns 'exit code N' + the end of the output."""
        res = await self.run(command, folder, timeout)
        return f"exit code {res['code']}\n{res['output'][-6000:]}"

    async def run(self, command: str, folder: str = ".", timeout: int = 1800) -> dict:
        """Same as run_command, for agents that need the structured result."""
        env = dict(self.extra_env)
        if self.extra_path:
            env["PATH"] = os.pathsep.join(self.extra_path) + os.pathsep + os.environ.get("PATH", "")
        res = await _run(command, self._path(folder), self.task_id, self.node, timeout, env)
        self.commands.append({"command": command, "folder": folder, "exit_code": res["code"], "seconds": res["seconds"],
                              "output_tail": res["output"][-3000:]})
        return res

    async def install_toolchain(self, tool: str, version: str = "") -> str:
        """Download a portable toolchain and put it on PATH for the following commands of this run."""
        try:
            got = toolchain_installer.ensure(tool.lower(), version or None)
        except Exception as e:  # noqa: BLE001
            return f"could not install {tool}: {e}"
        self.extra_path = [str(b) for b in got["bin"]] + self.extra_path
        self.extra_env.update(got["env"])
        return f"installed {got['label']} at {got['home']} – it is now on PATH for run_command"
