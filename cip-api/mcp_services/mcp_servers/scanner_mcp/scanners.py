"""
Security scanners used by the Scanner MCP server (and called in-process when the server is not running).

    SAST       semgrep · bandit (Python) · codeql
    quality    ruff (Python) · eslint (JS/TS, the repo's own config)
    deps       trivy-fs (all ecosystems + IaC) · osv-scanner · pip-audit · npm-audit · snyk
    secrets    gitleaks · trufflehog
    platforms  sonarqube (your server) · github-alerts (Dependabot, code scanning, secret scanning)
    image      trivy-image (used by the container agent)

Every scanner is `async def x(path, ctx) -> {"tool", "status": ok|error|skipped, "message", "findings": [...]}`;
a finding is {scanner, category, severity, title, file, line, rule_id, package, installed_version, fixed_version,
description, recommendation}. Secret values are never returned.

Tools are looked up in cip-api/.scanners (pip tools: Scripts/ or bin/; downloaded binaries: bin/; CodeQL: codeql/),
then on PATH, then their official Docker image. A tool that is not available is reported as `skipped` with how to
install it – the run continues.
"""

import asyncio
import base64
import json
import os
import shutil
import tempfile
from pathlib import Path

import httpx

from core.settings import env

SCANNER_HOME = Path(__file__).resolve().parents[3] / ".scanners"
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_SEV = {"ERROR": "HIGH", "WARNING": "MEDIUM", "WARN": "MEDIUM", "NOTE": "LOW", "MODERATE": "MEDIUM",
        "INFORMATIONAL": "INFO", "UNKNOWN": "LOW", "BLOCKER": "CRITICAL", "MAJOR": "MEDIUM", "MINOR": "LOW"}
INSTALL_HINT = "run: .venv\\Scripts\\python scripts\\install_scanners.py (or start Docker for the image fallback)"
PIP_HINT = "run: .scanners\\Scripts\\pip install -r requirements-scanners.txt"


# ------------------------------------------------------------------ helpers
def sev(value, default: str = "MEDIUM") -> str:
    v = str(value or "").upper()
    v = _SEV.get(v, v)
    return v if v in SEVERITIES else default


def cvss(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "MEDIUM"
    return "CRITICAL" if s >= 9 else "HIGH" if s >= 7 else "MEDIUM" if s >= 4 else "LOW"


def _json(text: str, default=None):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _rel(path: str, root: str) -> str:
    p = str(path or "").replace("\\", "/")
    r = str(Path(root).resolve()).replace("\\", "/")
    return p[len(r) + 1:] if p.lower().startswith(r.lower() + "/") else p.removeprefix("/src/")


def find_tool(binary: str) -> str | None:
    for folder in ("bin", "Scripts", "codeql"):
        found = shutil.which(binary, path=str(SCANNER_HOME / folder))
        if found:
            return found
    return shutil.which(binary)


async def _run(argv: list[str], cwd: str | None = None, timeout: int = 1500, extra_env: dict | None = None):
    environ = {**os.environ, **(extra_env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=environ, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        return 127, "", f"{argv[0]}: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"timeout after {timeout}s"
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _docker_ok() -> bool:
    return bool(shutil.which("docker")) and (await _run(["docker", "info"], timeout=20))[0] == 0


async def _tool(binary: str, args: list[str], path: str, image: str | None = None, timeout: int = 1500,
                extra_env: dict | None = None):
    """Run `binary args` natively ({src} = the folder), else `docker run image` with the folder at /src; None if neither."""
    exe = find_tool(binary)
    if exe:
        return await _run([exe, *[a.replace("{src}", path) for a in args]], cwd=path, timeout=timeout, extra_env=extra_env)
    if image and await _docker_ok():
        envs = [x for k, v in (extra_env or {}).items() for x in ("-e", f"{k}={v}")]
        return await _run(["docker", "run", "--rm", "-v", f"{Path(path).resolve()}:/src", *envs, image,
                           *[a.replace("{src}", "/src") for a in args]], timeout=timeout)
    return None


def result(tool: str, findings: list[dict] | None = None, status: str = "ok", message: str = "") -> dict:
    findings = findings or []
    if status == "ok" and not message:
        message = f"{len(findings)} findings"
    return {"tool": tool, "status": status, "message": message, "findings": findings}


def skipped(tool: str, why: str) -> dict:
    return result(tool, status="skipped", message=why)


def finding(scanner: str, category: str, severity: str, title: str, **kw) -> dict:
    return {"scanner": scanner, "category": category, "severity": severity, "title": str(title)[:200],
            "file": kw.get("file", ""), "line": int(kw.get("line") or 0), "rule_id": str(kw.get("rule_id") or ""),
            "package": kw.get("package", ""), "installed_version": kw.get("installed_version", ""),
            "fixed_version": kw.get("fixed_version", ""), "description": str(kw.get("description") or "")[:600],
            "recommendation": kw.get("recommendation", ""), "snippet": str(kw.get("snippet") or "")[:600]}


def _components(path: str, ctx: dict, *languages: str) -> list[Path]:
    """Folders of the planned components in these languages (the whole repo if the planner gave none)."""
    comps = [c for c in (ctx.get("components") or []) if c.get("language") in languages]
    return list(dict.fromkeys((Path(path) / c.get("path", ".")).resolve() for c in comps)) or [Path(path).resolve()]


# ------------------------------------------------------------------ SAST
async def semgrep(path: str, ctx: dict) -> dict:
    """Semgrep rule sets for the repo's languages; bundled CIP rules when the registry is unreachable."""
    configs = ctx.get("semgrep_configs") or ["p/default"]
    args = ["scan", "--json", "--quiet", "--metrics=off", "--disable-version-check"]
    for c in configs:
        args += ["--config", c]
    res = await _tool("semgrep", args + ["{src}"], path, "semgrep/semgrep")
    if res is None:
        return skipped("semgrep", f"semgrep not installed – {PIP_HINT}")
    data = _json(res[1], {})
    note = ""
    if not data.get("results") and (data.get("errors") or not data):
        rules = Path(path) / ".cip-semgrep-rules.yml"
        shutil.copy(Path(__file__).with_name("semgrep_rules.yml"), rules)
        res2 = await _tool("semgrep", ["scan", "--json", "--quiet", "--metrics=off", "--config", "{src}/.cip-semgrep-rules.yml",
                                       "--exclude", ".cip-semgrep-rules.yml", "{src}"], path, "semgrep/semgrep")
        rules.unlink(missing_ok=True)
        data = _json(res2[1], None) if res2 else None
        if data is None:
            return result("semgrep", status="error", message=(res[2] or res[1])[-500:] or "semgrep produced no output")
        note = " (bundled CIP rules – the Semgrep registry was unreachable)"
    findings = [finding("semgrep", "sast", sev(r["extra"].get("severity"), "LOW"), r["extra"].get("message", ""),
                        file=_rel(r["path"], path), line=r["start"]["line"], rule_id=r["check_id"].split(".")[-1],
                        description=r["extra"].get("message", ""), recommendation=r["extra"].get("fix") or "",
                        snippet=r["extra"].get("lines", "")) for r in data.get("results", [])]
    return result("semgrep", findings, message=f"{len(findings)} findings{note}")


async def bandit(path: str, ctx: dict) -> dict:
    """Python security linter."""
    if not any(Path(path).rglob("*.py")):
        return skipped("bandit", "no Python files")
    skip = ",".join(f"*/{d}/*" for d in ("node_modules", ".venv", "venv", ".cip-venv", ".git", "tests", "test", ".cip"))
    res = await _tool("bandit", ["-r", "{src}", "-f", "json", "-q", "-x", skip], path)
    if res is None:
        return skipped("bandit", f"bandit not installed – {PIP_HINT}")
    data = _json(res[1], None)
    if data is None:
        return result("bandit", status="error", message=(res[2] or res[1])[-500:])
    return result("bandit", [finding("bandit", "sast", sev(r.get("issue_severity")), r.get("issue_text", ""),
                                     file=_rel(r.get("filename"), path), line=r.get("line_number"), rule_id=r.get("test_id"),
                                     description=r.get("issue_text"), snippet=r.get("code"),
                                     recommendation=r.get("more_info", "")) for r in data.get("results", [])])


def parse_sarif(data: dict, scanner: str, root: str) -> list[dict]:
    out = []
    for run in (data or {}).get("runs", []):
        rules = {r.get("id"): r for r in (run.get("tool", {}).get("driver", {}).get("rules") or [])}
        for r in run.get("results", []):
            rule = rules.get(r.get("ruleId"), {})
            score = rule.get("properties", {}).get("security-severity")
            loc = ((r.get("locations") or [{}])[0].get("physicalLocation") or {})
            out.append(finding(scanner, "sast", cvss(score) if score else sev(r.get("level")),
                               rule.get("shortDescription", {}).get("text") or r.get("ruleId", ""),
                               file=_rel(loc.get("artifactLocation", {}).get("uri", ""), root),
                               line=loc.get("region", {}).get("startLine"), rule_id=r.get("ruleId"),
                               description=r.get("message", {}).get("text", ""), recommendation=rule.get("helpUri", "")))
    return out


async def codeql(path: str, ctx: dict) -> dict:
    """GitHub CodeQL security-extended queries (Python, JavaScript/TypeScript, Java, Go, C#)."""
    exe = find_tool("codeql")
    if not exe:
        return skipped("codeql", "CodeQL CLI not installed – run scripts\\install_scanners.py --codeql (≈1 GB). "
                                 "Free for open source; private code needs GitHub Advanced Security")
    langs = {"Python": "python", "JavaScript": "javascript", "TypeScript": "javascript", "Java": "java", "Go": "go", "C#": "csharp"}
    wanted = sorted({langs[c["language"]] for c in ctx.get("components") or [] if c.get("language") in langs}) or ["python"]
    findings, errors = [], []
    with tempfile.TemporaryDirectory(prefix="cip-codeql-") as tmp:
        for lang in wanted:
            db, sarif = Path(tmp) / f"db-{lang}", Path(tmp) / f"{lang}.sarif"
            create = [exe, "database", "create", str(db), f"--language={lang}", f"--source-root={path}", "--overwrite"]
            if lang in ("java", "csharp"):
                create.append("--build-mode=none")
            code, _, err = await _run(create, timeout=2400)
            if code:
                errors.append(f"{lang}: {err[-200:]}")
                continue
            code, _, err = await _run([exe, "database", "analyze", str(db), f"codeql/{lang}-queries:codeql-suites/{lang}-security-extended.qls",
                                       "--format=sarif-latest", f"--output={sarif}", "--download"], timeout=3600)
            if code or not sarif.exists():
                errors.append(f"{lang}: {err[-200:]}")
                continue
            findings += parse_sarif(_json(sarif.read_text(encoding="utf-8"), {}), "codeql", path)
    if errors and not findings:
        return result("codeql", status="error", message="; ".join(errors)[:500])
    return result("codeql", findings, message=f"{len(findings)} findings ({', '.join(wanted)})" + (f"; {'; '.join(errors)[:200]}" if errors else ""))


# ------------------------------------------------------------------ code quality (reported, never blocks the gate)
async def ruff(path: str, ctx: dict) -> dict:
    if not any(Path(path).rglob("*.py")):
        return skipped("ruff", "no Python files")
    res = await _tool("ruff", ["check", "{src}", "--output-format", "json", "--exit-zero", "--no-cache",
                               "--select", "E,F,W,B,S", "--ignore", "E501,W291,W293,S101",
                               "--extend-exclude", ".venv,venv,.cip-venv,node_modules"], path)
    if res is None:
        return skipped("ruff", f"ruff not installed – {PIP_HINT}")
    data = _json(res[1], None)
    if data is None:
        return result("ruff", status="error", message=(res[2] or res[1])[-500:])
    bug = ("F821", "F822", "F823", "E9", "F63", "F7", "B006", "B008", "S")
    return result("ruff", [finding("ruff", "code_quality", "MEDIUM" if (r.get("code") or "").startswith(bug) else "LOW",
                                   f"{r.get('code')}: {r.get('message')}", file=_rel(r.get("filename"), path),
                                   line=(r.get("location") or {}).get("row"), rule_id=r.get("code"),
                                   recommendation=(r.get("fix") or {}).get("message") or "") for r in data])


async def eslint(path: str, ctx: dict) -> dict:
    """The repo's own ESLint config (nothing to lint against without one)."""
    configs = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", ".eslintrc",
               ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml")
    npx = shutil.which("npx")
    findings, notes = [], []
    dirs = _components(path, ctx, "JavaScript", "TypeScript")
    for d in dirs:
        if not any((d / c).exists() for c in configs):
            notes.append(f"{_rel(str(d), path) or '.'}: no ESLint config")
            continue
        if not npx:
            return skipped("eslint", "Node.js / npx not installed")
        if not (d / "node_modules").exists():
            await _run([shutil.which("npm") or "npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=str(d), timeout=900)
        code, out, err = await _run([npx, "--no-install", "eslint", ".", "-f", "json"], cwd=str(d), timeout=900)
        for f in _json(out, []) or []:
            for m in f.get("messages", []):
                rule = m.get("ruleId") or "parse-error"
                security = rule.startswith("security/") or rule in ("no-eval", "no-implied-eval", "no-new-func", "react/no-danger")
                findings.append(finding("eslint", "sast" if security else "code_quality",
                                        ("MEDIUM" if security else "LOW") if m.get("severity") == 2 else "INFO",
                                        f"{rule}: {m.get('message', '')}", file=_rel(f.get("filePath"), path), line=m.get("line"),
                                        rule_id=rule))
    if not findings and len(notes) == len(dirs):
        return skipped("eslint", "; ".join(notes))
    return result("eslint", findings)


# ------------------------------------------------------------------ dependencies
async def trivy_fs(path: str, ctx: dict) -> dict:
    """Dependency CVEs of every ecosystem + Dockerfile / IaC misconfigurations."""
    java = any(Path(path).rglob("pom.xml")) or any(Path(path).rglob("build.gradle*"))
    args = ["fs", "--scanners", "vuln,misconfig", "--format", "json", "--quiet", "--skip-dirs", "**/node_modules",
            "--skip-dirs", "**/.venv"] + (["--offline-scan"] if java else []) + ["{src}"]
    res = await _tool("trivy", args, path, "aquasec/trivy:latest")
    if res is None:
        return skipped("trivy-fs", f"trivy not installed – {INSTALL_HINT}")
    return _parse_trivy(res, path, "trivy-fs")


async def trivy_image_scan(image: str) -> dict:
    """OS + library CVEs inside a built container image (container agent)."""
    exe = find_tool("trivy")
    if exe:
        res = await _run([exe, "image", "--scanners", "vuln", "--format", "json", "--quiet", image])
    elif await _docker_ok():
        res = await _run(["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock", "aquasec/trivy:latest",
                          "image", "--scanners", "vuln", "--format", "json", "--quiet", image])
    else:
        return skipped("trivy-image", f"trivy not installed – {INSTALL_HINT}")
    return _parse_trivy(res, ".", "trivy-image")


def _parse_trivy(res, root: str, name: str) -> dict:
    data = _json(res[1], None)
    if data is None:
        msg = res[2].strip()[-400:]
        if "failed to download vulnerability DB" in res[2]:
            msg = "Trivy could not download its vulnerability database (needs internet access to ghcr.io / mirror.gcr.io)"
        return result(name, status="error", message=msg)
    findings = []
    category = "container" if name == "trivy-image" else "dependency"
    for r in data.get("Results") or []:
        for v in r.get("Vulnerabilities") or []:
            findings.append(finding(name, category, sev(v.get("Severity"), "LOW"),
                                    f"{v.get('PkgName')} {v.get('InstalledVersion')} – {v.get('Title') or v.get('VulnerabilityID')}",
                                    file=_rel(r.get("Target", ""), root), rule_id=v.get("VulnerabilityID"), package=v.get("PkgName"),
                                    installed_version=v.get("InstalledVersion"), fixed_version=v.get("FixedVersion") or "",
                                    description=v.get("Description"),
                                    recommendation=f"upgrade {v.get('PkgName')} to {v['FixedVersion']}" if v.get("FixedVersion") else ""))
        for m in r.get("Misconfigurations") or []:
            findings.append(finding(name, "misconfiguration", sev(m.get("Severity"), "LOW"), m.get("Title", ""),
                                    file=_rel(r.get("Target", ""), root), line=(m.get("CauseMetadata") or {}).get("StartLine"),
                                    rule_id=m.get("ID"), description=m.get("Description"), recommendation=m.get("Resolution", "")))
    return result(name, findings)


async def osv_scanner(path: str, ctx: dict) -> dict:
    """OSV.dev advisories for every lock file in the repo."""
    res = await _tool("osv-scanner", ["scan", "source", "-r", "--format", "json", "{src}"], path, "ghcr.io/google/osv-scanner:latest")
    if res is None:
        return skipped("osv-scanner", f"osv-scanner not installed – {INSTALL_HINT}")
    data = _json(res[1], None)
    if data is None:
        if "no package sources found" in (res[1] + res[2]).lower():
            return skipped("osv-scanner", "no lock files / manifests found")
        return result("osv-scanner", status="error", message=(res[2] or res[1])[-500:])
    findings = []
    for r in data.get("results") or []:
        src = _rel(r.get("source", {}).get("path", ""), path)
        for p in r.get("packages") or []:
            pkg = p.get("package", {})
            group = {i: g.get("max_severity") for g in p.get("groups") or [] for i in g.get("ids", [])}
            for v in p.get("vulnerabilities") or []:
                s = (v.get("database_specific") or {}).get("severity")
                findings.append(finding("osv-scanner", "dependency", sev(s) if s else cvss(group.get(v.get("id"))),
                                        f"{pkg.get('name')} {pkg.get('version')} – {v.get('id')}: {v.get('summary', '')}",
                                        file=src, rule_id=v.get("id"), package=pkg.get("name", ""),
                                        installed_version=pkg.get("version", ""), description=v.get("details"),
                                        recommendation=f"https://osv.dev/vulnerability/{v.get('id')}"))
    return result("osv-scanner", findings)


async def pip_audit(path: str, ctx: dict) -> dict:
    """Python dependency CVEs (PyPA advisory DB)."""
    findings, ran = [], False
    for d in _components(path, ctx, "Python"):
        reqs = sorted(d.glob("requirements*.txt"))
        args = [a for r in reqs for a in ("-r", str(r))] or ([str(d)] if (d / "pyproject.toml").exists() else [])
        if not args:
            continue
        res = await _tool("pip-audit", args + ["-f", "json", "--progress-spinner", "off", "--desc", "on"], path, timeout=1500)
        if res is None:
            return skipped("pip-audit", f"pip-audit not installed – {PIP_HINT}")
        ran = True
        data = _json(res[1], None)
        if data is None:
            return result("pip-audit", status="error", message=(res[2] or res[1])[-500:])
        for dep in (data.get("dependencies", []) if isinstance(data, dict) else data):
            for v in dep.get("vulns", []):
                fixed = ", ".join(v.get("fix_versions") or [])
                findings.append(finding("pip-audit", "dependency", "MEDIUM", f"{dep['name']} {dep.get('version', '')} – {v.get('id')}",
                                        file=_rel(str(reqs[0]) if reqs else str(d / "pyproject.toml"), path), rule_id=v.get("id"),
                                        package=dep["name"], installed_version=dep.get("version", ""), fixed_version=fixed,
                                        description=v.get("description"),
                                        recommendation=f"upgrade {dep['name']} to {fixed}" if fixed else "no fixed version yet"))
    return result("pip-audit", findings) if ran else skipped("pip-audit", "no requirements*.txt / pyproject.toml")


async def npm_audit(path: str, ctx: dict) -> dict:
    """Node dependency CVEs (resolves a lock file first when the repo has none)."""
    npm = shutil.which("npm")
    dirs = [d for d in _components(path, ctx, "JavaScript", "TypeScript") if (d / "package.json").exists()]
    if not dirs:
        return skipped("npm-audit", "no package.json")
    if not npm:
        return skipped("npm-audit", "Node.js / npm not installed")
    findings, notes = [], []
    for d in dirs:
        where = _rel(str(d), path)
        if not any((d / f).exists() for f in ("package-lock.json", "npm-shrinkwrap.json")):
            await _run([npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=str(d), timeout=900)
            notes.append(f"{where or '.'}: lock file resolved by CIP")
        _, out, err = await _run([npm, "audit", "--json"], cwd=str(d), timeout=900)
        data = _json(out, None)
        if data is None:
            notes.append(f"{where or '.'}: {err[-150:]}")
            continue
        for pkg, v in (data.get("vulnerabilities") or {}).items():
            for via in v.get("via", []):
                if isinstance(via, dict):
                    fix = v.get("fixAvailable")
                    findings.append(finding("npm-audit", "dependency", sev(via.get("severity") or v.get("severity")),
                                            f"{pkg} {via.get('range', '')} – {via.get('title', '')}",
                                            file=f"{where + '/' if where else ''}package.json", rule_id=via.get("source"), package=pkg,
                                            installed_version=v.get("range", ""), description=via.get("title"),
                                            fixed_version=fix.get("version", "") if isinstance(fix, dict) else "",
                                            recommendation=f"npm install {fix['name']}@{fix['version']}" if isinstance(fix, dict)
                                            else "npm audit fix" if fix else "no fix available yet"))
    return result("npm-audit", findings, message=f"{len(findings)} findings" + (f" · {'; '.join(notes)}" if notes else ""))


async def snyk(path: str, ctx: dict) -> dict:
    token = env("snyk_token")
    if not token:
        return skipped("snyk", "snyk_token not set in .env (free account: snyk.io → Account settings → Auth token)")
    res = await _tool("snyk", ["test", "--all-projects", "--json", "{src}"], path, "snyk/snyk:linux", timeout=1500,
                      extra_env={"SNYK_TOKEN": token})
    if res is None:
        return skipped("snyk", f"snyk CLI not installed – {INSTALL_HINT}")
    data = _json(res[1], None)
    if data is None:
        return result("snyk", status="error", message=(res[2] or res[1])[-500:])
    findings, seen = [], set()
    for proj in data if isinstance(data, list) else [data]:
        for v in proj.get("vulnerabilities") or []:
            if (v.get("id"), v.get("packageName")) in seen:
                continue
            seen.add((v.get("id"), v.get("packageName")))
            findings.append(finding("snyk", "dependency", sev(v.get("severity")), f"{v.get('packageName')} {v.get('version')} – {v.get('title')}",
                                    file=proj.get("displayTargetFile", ""), rule_id=v.get("id"), package=v.get("packageName", ""),
                                    installed_version=v.get("version", ""), fixed_version=", ".join(v.get("fixedIn") or []),
                                    recommendation=f"https://security.snyk.io/vuln/{v.get('id')}"))
    return result("snyk", findings)


# ------------------------------------------------------------------ secrets
async def gitleaks(path: str, ctx: dict) -> dict:
    report = Path(path).resolve() / ".cip-gitleaks.json"
    res = await _tool("gitleaks", ["detect", "--no-git", "--source", "{src}", "--report-format", "json",
                                   "--report-path", "{src}/.cip-gitleaks.json", "--exit-code", "0", "--redact"], path, "zricethezav/gitleaks")
    if res is None:
        return skipped("gitleaks", f"gitleaks not installed – {INSTALL_HINT}")
    try:
        data = _json(report.read_text(encoding="utf-8") or "[]", [])
    except OSError:
        return result("gitleaks", status="error", message=res[2][-400:])
    finally:
        report.unlink(missing_ok=True)
    return result("gitleaks", [finding("gitleaks", "secret", "HIGH", f"Secret: {f.get('Description')}", file=_rel(f.get("File"), path),
                                       line=f.get("StartLine"), rule_id=f.get("RuleID"),
                                       description="A credential is written in the source code (value redacted).",
                                       recommendation="Remove it, rotate the credential, load it from an environment variable / secret store.")
                               for f in data], message=f"{len(data)} secrets")


async def trufflehog(path: str, ctx: dict) -> dict:
    """800+ secret detectors (filesystem mode, no live verification)."""
    exclude = Path(path) / ".cip-trufflehog-exclude"
    exclude.write_text("node_modules\n\\.git/\n\\.venv\n\\.cip-venv\n", encoding="utf-8")
    res = await _tool("trufflehog", ["filesystem", "{src}", "--json", "--no-verification", "--no-update",
                                     "--exclude-paths", "{src}/.cip-trufflehog-exclude"], path, "trufflesecurity/trufflehog:latest")
    exclude.unlink(missing_ok=True)
    if res is None:
        return skipped("trufflehog", f"trufflehog not installed – {INSTALL_HINT}")
    findings = []
    for line in res[1].splitlines():
        r = _json(line, None)
        if isinstance(r, dict) and "DetectorName" in r:
            fs = ((r.get("SourceMetadata") or {}).get("Data") or {}).get("Filesystem") or {}
            findings.append(finding("trufflehog", "secret", "HIGH", f"Hard-coded secret: {r.get('DetectorName')}",
                                    file=_rel(fs.get("file", ""), path), line=fs.get("line"), rule_id=r.get("DetectorName"),
                                    description="Match redacted by CIP",
                                    recommendation="Remove the secret from source, rotate it, and load it from a secret manager."))
    if not findings and res[0] not in (0, 183) and res[2].strip():
        return result("trufflehog", status="error", message=res[2][-400:])
    return result("trufflehog", findings, message=f"{len(findings)} secrets")


# ------------------------------------------------------------------ platforms
async def sonarqube(path: str, ctx: dict) -> dict:
    """sonar-scanner against your SonarQube server; issues + quality gate read back."""
    host, token = env("sonar_host_url").rstrip("/"), env("sonar_token")
    if not host or not token:
        return skipped("sonarqube", "set sonar_host_url and sonar_token in .env "
                                    "(local server: docker run -d --name sonarqube -p 9000:9000 sonarqube:community)")
    auth = {"Authorization": "Basic " + base64.b64encode(f"{token}:".encode()).decode()}
    async with httpx.AsyncClient(timeout=60, headers=auth) as http:
        try:
            status = (await http.get(f"{host}/api/system/status")).json().get("status")
        except (httpx.HTTPError, ValueError) as e:
            return skipped("sonarqube", f"SonarQube not reachable at {host} ({e})")
        if status != "UP":
            return skipped("sonarqube", f"SonarQube at {host} is {status} – wait until it is up")
        key = "cip-" + "".join(ch if ch.isalnum() or ch in "_.:-" else "-" for ch in ctx.get("project", Path(path).name))
        props = [f"-Dsonar.projectKey={key}", "-Dsonar.sources=.", "-Dsonar.qualitygate.wait=true", "-Dsonar.scm.disabled=true",
                 "-Dsonar.java.binaries=.", "-Dsonar.exclusions=**/node_modules/**,**/dist/**,**/build/**,**/target/**,**/.cip/**"]
        exe = find_tool("sonar-scanner")
        if exe:
            code, out, err = await _run([exe, f"-Dsonar.host.url={host}", *props], cwd=path, timeout=2400, extra_env={"SONAR_TOKEN": token})
        elif await _docker_ok():
            inner = host.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
            code, out, err = await _run(["docker", "run", "--rm", "--add-host=host.docker.internal:host-gateway", "-e", f"SONAR_HOST_URL={inner}",
                                         "-e", f"SONAR_TOKEN={token}", "-v", f"{Path(path).resolve()}:/usr/src",
                                         "sonarsource/sonar-scanner-cli:latest", *props], timeout=2400)
        else:
            return skipped("sonarqube", "sonar-scanner not installed and Docker not running")
        try:
            issues = (await http.get(f"{host}/api/issues/search", params={"componentKeys": key, "resolved": "false", "ps": 500})).json()
            gate = (await http.get(f"{host}/api/qualitygates/project_status", params={"projectKey": key})).json()
        except (httpx.HTTPError, ValueError) as e:
            return result("sonarqube", status="error", message=f"scanner exit {code}; reading issues failed: {e}")
    findings = []
    for i in issues.get("issues", []):
        impact = (i.get("impacts") or [{}])[0]
        vuln = i.get("type") == "VULNERABILITY" or impact.get("softwareQuality") == "SECURITY"
        s = sev(impact.get("severity") or i.get("severity"))
        findings.append(finding("sonarqube", "sast" if vuln else "code_quality", s if vuln else "LOW", i.get("message", ""),
                                file=i.get("component", "").split(":", 1)[-1], line=i.get("line"), rule_id=i.get("rule"),
                                recommendation=f"{host}/project/issues?id={key}&open={i.get('key')}"))
    gate_status = (gate.get("projectStatus") or {}).get("status", "?")
    return result("sonarqube", findings, message=f"{len(findings)} issues · quality gate {gate_status} · {host}/dashboard?id={key}")


async def github_alerts(path: str, ctx: dict) -> dict:
    """Open Dependabot, code-scanning and secret-scanning alerts GitHub already has for the repo."""
    slug, token = ctx.get("github_repo"), env("github_token")
    if not slug:
        return skipped("github-alerts", "source is not a GitHub repository")
    if not token:
        return skipped("github-alerts", "github_token not set in .env")
    api = f"https://api.github.com/repos/{slug}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    findings, notes = [], []
    async with httpx.AsyncClient(timeout=60, headers=headers) as http:
        for kind in ("dependabot", "code-scanning", "secret-scanning"):
            r = await http.get(f"{api}/{kind}/alerts", params={"state": "open", "per_page": 100})
            if r.status_code != 200:
                notes.append(f"{kind}: HTTP {r.status_code}" + (" (not enabled or token lacks access)" if r.status_code in (403, 404) else ""))
                continue
            for a in r.json():
                if kind == "dependabot":
                    adv, vul = a.get("security_advisory", {}), a.get("security_vulnerability", {})
                    findings.append(finding("github-alerts", "dependency", sev(adv.get("severity")),
                                            f"Dependabot: {vul.get('package', {}).get('name')} – {adv.get('summary', '')}",
                                            file=a.get("dependency", {}).get("manifest_path", ""), rule_id=adv.get("ghsa_id"),
                                            package=vul.get("package", {}).get("name", ""),
                                            fixed_version=(vul.get("first_patched_version") or {}).get("identifier", ""),
                                            recommendation=a.get("html_url", "")))
                elif kind == "code-scanning":
                    rule, loc = a.get("rule", {}), (a.get("most_recent_instance") or {}).get("location", {})
                    findings.append(finding("github-alerts", "sast", sev(rule.get("security_severity_level") or rule.get("severity")),
                                            f"Code scanning: {rule.get('description', '')}", file=loc.get("path", ""),
                                            line=loc.get("start_line"), rule_id=rule.get("id"), recommendation=a.get("html_url", "")))
                else:   # secret scanning – the alert's `secret` value is deliberately not copied
                    findings.append(finding("github-alerts", "secret", "HIGH",
                                            f"Secret scanning: {a.get('secret_type_display_name') or a.get('secret_type')}",
                                            rule_id=a.get("secret_type"), description="GitHub detected a committed credential (value not shown).",
                                            recommendation=f"Rotate the credential, then close the alert: {a.get('html_url', '')}"))
    if len(notes) == 3:
        return skipped("github-alerts", "; ".join(notes))
    return result("github-alerts", findings, message=f"{len(findings)} open alerts" + (f" · {'; '.join(notes)}" if notes else ""))


# ------------------------------------------------------------------ catalogue
CATALOG = {
    #  name           function       label                                       category      runs by default when …
    "semgrep":       (semgrep,       "Semgrep (SAST)",                           "sast",       "always"),
    "bandit":        (bandit,        "Bandit (Python SAST)",                     "sast",       "Python"),
    "codeql":        (codeql,        "CodeQL (SAST)",                            "sast",       "installed"),
    "ruff":          (ruff,          "Ruff (Python lint)",                       "quality",    "Python"),
    "eslint":        (eslint,        "ESLint (JS/TS lint)",                      "quality",    "Node"),
    "trivy-fs":      (trivy_fs,      "Trivy (dependencies + IaC)",               "dependency", "always"),
    "osv-scanner":   (osv_scanner,   "OSV-Scanner (dependencies)",               "dependency", "always"),
    "pip-audit":     (pip_audit,     "pip-audit (Python dependencies)",          "dependency", "Python"),
    "npm-audit":     (npm_audit,     "npm audit (Node dependencies)",            "dependency", "Node"),
    "snyk":          (snyk,          "Snyk Open Source",                         "dependency", "configured"),
    "gitleaks":      (gitleaks,      "Gitleaks (secrets)",                       "secret",     "always"),
    "trufflehog":    (trufflehog,    "TruffleHog (secrets)",                     "secret",     "always"),
    "sonarqube":     (sonarqube,     "SonarQube",                                "platform",   "configured"),
    "github-alerts": (github_alerts, "GitHub alerts (Dependabot, code + secret scanning)", "platform", "configured"),
}


def available(name: str) -> bool:
    """Whether a scanner that needs a token / server / big install is set up on this machine."""
    return {"codeql": bool(find_tool("codeql")), "snyk": bool(env("snyk_token")),
            "sonarqube": bool(env("sonar_host_url") and env("sonar_token")), "github-alerts": bool(env("github_token"))}.get(name, True)


async def list_scanners() -> dict:
    """Every scanner with its category, default rule and whether its tool is installed / configured."""
    binary = {"trivy-fs": "trivy", "eslint": "npx", "npm-audit": "npm", "github-alerts": None, "sonarqube": None}
    out = []
    for name, (_, label, category, when) in CATALOG.items():
        exe = binary.get(name, name)
        out.append({"name": name, "label": label, "category": category, "default_when": when, "configured": available(name),
                    "installed": True if exe is None else bool(find_tool(exe))})
    return {"scanners": out}


def default_scanners(languages: set[str], github: bool) -> list[str]:
    node = bool(languages & {"JavaScript", "TypeScript"})
    pick = []
    for name, (_, _, _, when) in CATALOG.items():
        if when == "always" or (when == "Python" and "Python" in languages) or (when == "Node" and node) \
                or (when in ("installed", "configured") and available(name) and (name != "github-alerts" or github)):
            pick.append(name)
    return pick


async def run_scanner(name: str, path: str, context: dict | None = None) -> dict:
    """Run one scanner of the catalogue on a folder; a crash becomes an `error` result, never an exception."""
    if name not in CATALOG:
        return result(name, status="error", message=f"unknown scanner (known: {', '.join(CATALOG)})")
    try:
        return await CATALOG[name][0](path, context or {})
    except Exception as e:  # noqa: BLE001 – one broken scanner must not stop the others
        return result(name, status="error", message=f"{type(e).__name__}: {e}")


SCANNERS = {"run_scanner": run_scanner, "list_scanners": list_scanners, "trivy_image_scan": trivy_image_scan}
