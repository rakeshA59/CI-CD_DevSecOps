"""
Docker operations used by the Docker MCP server (and in-process when the server is not running).
All functions are async and return plain dicts.
"""

import asyncio
import shutil
import time
import urllib.request


async def _docker(*args: str, timeout: int = 2400) -> tuple[int, str]:
    if not shutil.which("docker"):
        return 127, "docker is not installed"
    proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s"
    return proc.returncode, out.decode("utf-8", "replace")


async def docker_status() -> dict:
    """Is the Docker daemon running?"""
    code, out = await _docker("info", "--format", "{{.ServerVersion}}", timeout=20)
    return {"running": code == 0, "version": out.strip() if code == 0 else "", "message": "" if code == 0 else out[-300:]}


async def docker_build(context: str, tag: str, dockerfile: str = "Dockerfile") -> dict:
    """Build an image and make sure it is in the local image store (buildx builders may only cache it)."""
    code, out = await _docker("build", "-t", tag, "-f", f"{context}/{dockerfile}", context)
    if code != 0:
        return {"built": False, "image": tag, "log": out[-8000:]}
    if (await _docker("image", "inspect", tag, timeout=30))[0] != 0:
        code, out2 = await _docker("build", "--load", "-t", tag, "-f", f"{context}/{dockerfile}", context)
        out += "\n--- rebuilt with --load ---\n" + out2
        if (await _docker("image", "inspect", tag, timeout=30))[0] != 0:
            return {"built": False, "image": tag, "log": out[-8000:] + "\nimage not in the local store – run `docker buildx use default`"}
    _, size = await _docker("image", "inspect", tag, "--format", "{{.Size}}", timeout=30)
    return {"built": True, "image": tag, "size_mb": round(int(size.strip()) / 1e6, 1) if size.strip().isdigit() else None,
            "log": out[-4000:]}


async def docker_run(image: str, name: str, network: str, port: int, env: dict | None = None, alias: str = "") -> dict:
    """Run a container on a private network, publish its port on 127.0.0.1 and wait until it answers HTTP."""
    await _docker("network", "create", network, timeout=30)
    args = ["run", "-d", "--name", name, "--network", network, "--network-alias", alias or name]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    if port:
        args += ["-p", f"127.0.0.1::{port}"]
    code, out = await _docker(*args, image, timeout=300)
    if code != 0:
        return {"status": "failed", "message": out[-600:]}
    url = ""
    if port:
        _, mapped = await _docker("port", name, str(port), timeout=30)
        url = f"http://127.0.0.1:{mapped.strip().splitlines()[0].rsplit(':', 1)[-1]}" if mapped.strip() else ""
    deadline, status = time.time() + 90, None
    while url and time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:      # noqa: S310 – local container
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception:  # noqa: BLE001
            status = None
        if status and status < 500:
            break
        if (await _docker("inspect", "-f", "{{.State.Running}}", name, timeout=20))[1].strip() != "true":
            break
        await asyncio.sleep(2)
    healthy = bool(status and status < 500) or (not port)
    _, logs = await _docker("logs", "--tail", "60", name, timeout=30)
    return {"status": "passed" if healthy else "failed", "url": url, "internal_url": f"http://{alias or name}:{port}",
            "http_status": status, "message": f"answered HTTP {status}" if healthy else "did not become healthy",
            "logs_tail": logs[-3000:]}


async def docker_remove(names: list[str], network: str = "") -> dict:
    """Remove containers (and the network) after the tests."""
    for n in names:
        await _docker("rm", "-f", n, timeout=60)
    if network:
        await _docker("network", "rm", network, timeout=60)
    return {"removed": names}


DOCKER_OPS = {"docker_status": docker_status, "docker_build": docker_build, "docker_run": docker_run,
              "docker_remove": docker_remove}
