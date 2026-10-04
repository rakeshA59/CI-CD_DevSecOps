"""Toolchain Installer – install the build toolchain a repo needs when this machine does not have it – no admin rights, no Docker.

    ensure("jdk", "17")  ->  {"home": ~/.cip/tools/jdk-17/…, "bin": [...], "env": {"JAVA_HOME": …}, "label": "JDK 17 (Temurin)"}

Downloads the official portable archive once into ~/.cip/tools (or CIP_TOOLS_DIR) and reuses it on every later run:

    jdk     Eclipse Temurin (Adoptium)          any major version the build file asks for (8 / 11 / 17 / 21)
    maven   Apache Maven 3.9.9                  binary zip from archive.apache.org
    gradle  Gradle 8.10.2                       only when the repo has no gradlew wrapper
    node    Node.js 20 LTS                      nodejs.org
    go      Go (version from go.mod)            go.dev

Behind a company proxy the standard HTTPS_PROXY variable is used. A company mirror can replace any URL in
config/pipeline.yaml → toolchain_urls: {jdk: "...{version}...{os}...{arch}...", maven: "...", ...}.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path


log = logging.getLogger("cip.provision")

MAVEN_VERSION, GRADLE_VERSION, NODE_VERSION = "3.9.9", "8.10.2", "20.18.0"
URLS = {
    "jdk": "https://api.adoptium.net/v3/binary/latest/{version}/ga/{os}/{arch}/jdk/hotspot/normal/eclipse",
    "maven": "https://archive.apache.org/dist/maven/maven-3/{version}/binaries/apache-maven-{version}-bin.zip",
    "gradle": "https://services.gradle.org/distributions/gradle-{version}-bin.zip",
    "node": "https://nodejs.org/dist/v{version}/node-v{version}-{node_plat}.{node_ext}",
    "go": "https://go.dev/dl/go{version}.{go_os}-{go_arch}.{go_ext}",
}
DEFAULT_VERSION = {"jdk": "17", "maven": MAVEN_VERSION, "gradle": GRADLE_VERSION, "node": NODE_VERSION, "go": "1.22.8"}
LABEL = {"jdk": "JDK {version} (Eclipse Temurin)", "maven": "Apache Maven {version}", "gradle": "Gradle {version}",
         "node": "Node.js {version}", "go": "Go {version}"}


class ProvisionError(RuntimeError):
    pass


def tools_dir() -> Path:
    return Path(os.getenv("CIP_TOOLS_DIR") or Path.home() / ".cip" / "tools")


def _platform() -> dict:
    system = platform.system().lower()
    osn = {"windows": "windows", "darwin": "mac"}.get(system, "linux")
    m = platform.machine().lower()
    arch = "aarch64" if m in ("arm64", "aarch64") else "x64"
    return {"os": osn, "arch": arch,
            "node_plat": {"windows": "win", "mac": "darwin", "linux": "linux"}[osn] + "-" + ("arm64" if arch == "aarch64" else "x64"),
            "node_ext": "zip" if osn == "windows" else "tar.gz",
            "go_os": {"windows": "windows", "mac": "darwin", "linux": "linux"}[osn], "go_arch": "arm64" if arch == "aarch64" else "amd64",
            "go_ext": "zip" if osn == "windows" else "tar.gz"}


def _home(root: Path) -> Path:
    """The folder inside the extracted archive that holds bin/ (archives contain one top folder; macOS JDKs nest Contents/Home)."""
    kids = [k for k in root.iterdir() if k.is_dir()]
    home = kids[0] if len(kids) == 1 else root
    if (home / "Contents" / "Home").is_dir():
        home = home / "Contents" / "Home"
    return home


def _bins(tool: str, home: Path) -> list[Path]:
    if tool == "node" and platform.system() == "Windows":
        return [home]
    return [home / "bin"]


def _extract(archive: Path, dest: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest)  # noqa: S202
    if platform.system() != "Windows":       # zip loses the executable bit
        for f in dest.rglob("*"):
            if f.is_file() and f.parent.name == "bin":
                f.chmod(f.stat().st_mode | 0o111)


def ensure(tool: str, version: str | None = None, cfg: dict | None = None) -> dict:
    """Make `tool` available (download + unpack once); returns its home, bin folders and environment."""
    version = str(version or DEFAULT_VERSION[tool])
    target = tools_dir() / f"{tool}-{version}"
    ready = target / ".cip_ready"
    label = LABEL[tool].format(version=version)
    if not ready.exists():
        url = ((cfg or {}).get("toolchain_urls") or {}).get(tool) or URLS[tool]
        url = url.format(version=version, **_platform())
        log.info("%s is not installed – downloading %s into %s", label, url, tools_dir())
        tmp = target.with_name(target.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        archive = tmp / "download"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cip-toolchain"})
            with urllib.request.urlopen(req, timeout=120) as r, archive.open("wb") as fh:   # noqa: S310 – fixed https URLs
                shutil.copyfileobj(r, fh, 1024 * 1024)
            _extract(archive, tmp / "x")
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(tmp, ignore_errors=True)
            raise ProvisionError(f"could not download {label} from {url}: {e}") from e
        archive.unlink(missing_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        (tmp / "x").rename(target)
        shutil.rmtree(tmp, ignore_errors=True)
        ready.write_text(url, encoding="utf-8")
    home = _home(target)
    env = {"JAVA_HOME": str(home)} if tool == "jdk" else {"MAVEN_HOME": str(home)} if tool == "maven" else \
        {"GOROOT": str(home)} if tool == "go" else {}
    return {"tool": tool, "version": version, "home": home, "bin": _bins(tool, home), "env": env, "label": label}


def find_in(bins: list[Path], name: str) -> str | None:
    """An executable inside the provisioned bin folders (mvn → mvn.cmd on Windows)."""
    order = (name + ".exe", name + ".cmd", name + ".bat") if os.name == "nt" else (name,)
    for b in bins:
        for cand in order:     # Windows: bin/mvn is a Unix shell script – running it gives WinError 193
            p = b / cand
            if p.is_file():
                return str(p)
    return None
