"""
Install every scanner DevOps uses into cip-api/.scanners – no admin rights, nothing added to the API's venv.

    python scripts\\install_scanners.py            # all of them except CodeQL
    python scripts\\install_scanners.py --codeql   # + CodeQL bundle (~1 GB download)
    python scripts\\install_scanners.py gitleaks trivy   # only these

    .scanners\\Scripts\\   semgrep, bandit, ruff, pip-audit   (own venv, from requirements-scanners.txt)
    .scanners\\bin\\       gitleaks, trivy, osv-scanner, trufflehog, snyk   (latest GitHub release binaries)
    .scanners\\codeql\\    CodeQL CLI + query packs

The scanner MCP server finds them there automatically. npm audit / ESLint use your Node.js install;
SonarQube and GitHub alerts need sonar_host_url + sonar_token / github_token in .env (no install).
A company proxy is picked up from HTTPS_PROXY.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
HOME = API_DIR / ".scanners"
BIN = HOME / "bin"
OS = {"windows": "windows", "darwin": "mac"}.get(platform.system().lower(), "linux")
EXE = ".exe" if OS == "windows" else ""
ARM = platform.machine().lower() in ("arm64", "aarch64")

#            GitHub repo                   release asset per OS (regex, case-insensitive)
RELEASES = {
    "gitleaks": ("gitleaks/gitleaks", {"windows": r"windows_x64\.zip$", "linux": r"linux_(arm64|x64)\.tar\.gz$",
                                       "mac": r"darwin_(arm64|x64)\.tar\.gz$"}),
    "trivy": ("aquasecurity/trivy", {"windows": r"windows-64bit\.zip$", "linux": r"linux-(arm64|64bit)\.tar\.gz$",
                                     "mac": r"macos-(arm64|64bit)\.tar\.gz$"}),
    "osv-scanner": ("google/osv-scanner", {"windows": r"windows_amd64\.exe$", "linux": r"linux_(arm64|amd64)$",
                                           "mac": r"darwin_(arm64|amd64)$"}),
    "trufflehog": ("trufflesecurity/trufflehog", {"windows": r"windows_amd64\.tar\.gz$", "linux": r"linux_(arm64|amd64)\.tar\.gz$",
                                                  "mac": r"darwin_(arm64|amd64)\.tar\.gz$"}),
    "snyk": ("snyk/cli", {"windows": r"^snyk-win\.exe$", "linux": r"^snyk-linux(-arm64)?$", "mac": r"^snyk-macos(-arm64)?$"}),
    "codeql": ("github/codeql-action", {"windows": r"^codeql-bundle-win64\.tar\.gz$", "linux": r"^codeql-bundle-linux64\.tar\.gz$",
                                        "mac": r"^codeql-bundle-osx64\.tar\.gz$"}),
}


def _token() -> str:
    for line in (API_DIR / ".env").read_text(encoding="utf-8").splitlines() if (API_DIR / ".env").exists() else []:
        if line.strip().lower().startswith("github_token="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return os.getenv("GITHUB_TOKEN", "")


def _get(url: str, accept: str = "application/vnd.github+json"):
    headers = {"User-Agent": "cip-install-scanners", "Accept": accept}
    if _token() and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {_token()}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=600)   # noqa: S310 – fixed https URLs


def pick_asset(assets: list[str], pattern: str) -> str | None:
    """The release asset for this OS / CPU (prefers arm64 builds on ARM, x64 otherwise)."""
    hits = [a for a in assets if re.search(pattern, a, re.I) and not re.search(r"\.(sha256|sig|pem|sbom|txt|json)$", a, re.I)]
    hits.sort(key=lambda a: ("arm64" in a.lower()) != ARM)
    return hits[0] if hits else None


def _extract(archive: Path, dest: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest)  # noqa: S202


def install_binary(tool: str) -> str:
    repo, patterns = RELEASES[tool]
    release = json.load(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
    names = [a["name"] for a in release.get("assets", [])]
    asset = pick_asset(names, patterns[OS])
    if not asset:
        raise RuntimeError(f"no {OS} build in {repo} {release.get('tag_name')} (assets: {', '.join(names[:8])} ...)")
    url = next(a["browser_download_url"] for a in release["assets"] if a["name"] == asset)
    print(f"  downloading {asset} ({release.get('tag_name')})...", flush=True)
    with tempfile.TemporaryDirectory(prefix="cip-scanner-") as tmp:
        download = Path(tmp) / asset
        with _get(url, "application/octet-stream") as r, download.open("wb") as fh:
            shutil.copyfileobj(r, fh, 1024 * 1024)
        if tool == "codeql":
            shutil.rmtree(HOME / "codeql", ignore_errors=True)
            _extract(download, HOME)                       # the bundle unpacks to codeql/
            target = HOME / "codeql" / f"codeql{EXE}"
        else:
            BIN.mkdir(parents=True, exist_ok=True)
            target = BIN / f"{tool}{EXE}"
            if asset.endswith((".zip", ".tar.gz", ".tgz")):
                _extract(download, Path(tmp) / "x")
                found = next((p for p in (Path(tmp) / "x").rglob(f"{tool}{EXE}") if p.is_file()), None)
                if not found:
                    raise RuntimeError(f"{tool}{EXE} not found inside {asset}")
                shutil.copy2(found, target)
            else:
                shutil.copy2(download, target)
    if OS != "windows":
        target.chmod(target.stat().st_mode | 0o111)
    return str(target)


def install_python_tools(force: bool = False) -> str:
    py = HOME / ("Scripts/python.exe" if OS == "windows" else "bin/python")
    if not py.exists():
        print("  creating the .scanners venv...", flush=True)
        venv.EnvBuilder(with_pip=True).create(HOME)
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"], check=False)
    subprocess.run([str(py), "-m", "pip", "install", *(["--force-reinstall"] if force else []),
                    "-r", str(API_DIR / "requirements-scanners.txt")], check=True)
    return str(py.parent)


def main() -> int:
    sys.stdout.reconfigure(errors="replace")       # old Windows consoles (cp1252) cannot print every character
    parser = argparse.ArgumentParser(description="Install CIP's security scanners into cip-api/.scanners")
    parser.add_argument("tools", nargs="*", help="only these (python, gitleaks, trivy, osv-scanner, trufflehog, snyk, codeql)")
    parser.add_argument("--codeql", action="store_true", help="also install the CodeQL bundle (~1 GB)")
    args = parser.parse_args()
    tools = args.tools or ["python", "gitleaks", "trivy", "osv-scanner", "trufflehog", "snyk"] + (["codeql"] if args.codeql else [])
    ok, failed = [], []
    for tool in tools:
        print(f"[{tool}]", flush=True)
        try:
            where = install_python_tools() if tool == "python" else install_binary(tool)
            ok.append(tool)
            print(f"  OK {where}")
        except Exception as e:  # noqa: BLE001 – keep going with the other tools
            failed.append(tool)
            print(f"  FAILED {tool}: {e}")
    print(f"\nInstalled: {', '.join(ok) or '-'}" + (f"\nFailed:    {', '.join(failed)} (those scanners fall back to Docker or are skipped)" if failed else ""))
    if shutil.which("npm") is None:
        print("Note: Node.js not found – npm audit and ESLint are skipped until Node.js is installed.")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
