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
    except asyncio.CancelledError:          # the run was stopped – do not leave the docker command running
        proc.kill()
        raise
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


async def docker_run(image: str, name: str, network: str, port: int, env: dict | None = None, alias: str = "",
                     keep: bool = False) -> dict:
    """Run a container on a private network, publish its port on 127.0.0.1 and wait until it answers HTTP.
    keep = restart it whenever Docker / the PC restarts (until it is stopped by hand) – for UAT."""
    await _docker("network", "create", network, timeout=30)
    args = ["run", "-d", "--name", name, "--network", network, "--network-alias", alias or name]
    if keep:
        args += ["--restart", "unless-stopped"]
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
        host_port = mapped.strip().splitlines()[0].rsplit(":", 1)[-1] if mapped.strip() else ""
        url = f"http://127.0.0.1:{host_port}" if host_port.isdigit() else ""      # not published = container exited / wrong port
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
    running = (await _docker("inspect", "-f", "{{.State.Running}}", name, timeout=20))[1].strip() == "true"
    healthy = bool(status and status < 500) or (not port)
    _, logs = await _docker("logs", "--tail", "60", name, timeout=30)
    return {"status": "passed" if healthy else "failed", "url": url, "internal_url": f"http://{alias or name}:{port}",
            "http_status": status, "message": f"answered HTTP {status}" if healthy else (
                "did not become healthy" if running else "the container exited right after starting – see the log tail"),
            "logs_tail": logs[-3000:]}


async def docker_remove(names: list[str], network: str = "") -> dict:
    """Remove containers (and the network) after the tests."""
    for n in names:
        await _docker("rm", "-f", n, timeout=60)
    if network:
        await _docker("network", "rm", network, timeout=60)
    return {"removed": names}


async def docker_registry(port: int = 5000) -> dict:
    """Make sure a local image registry (registry:2) runs on localhost:<port>; start it when it does not."""
    name = "cip-registry"
    if (await _docker("inspect", "-f", "{{.State.Running}}", name, timeout=20))[1].strip() == "true":
        return {"running": True, "registry": f"localhost:{port}", "message": "already running"}
    await _docker("rm", "-f", name, timeout=30)
    code, out = await _docker("run", "-d", "--restart", "unless-stopped", "--name", name, "-p", f"{port}:5000", "registry:2", timeout=600)
    return {"running": code == 0, "registry": f"localhost:{port}", "message": "started registry:2" if code == 0 else out[-500:]}


async def docker_push(image: str, registry: str, repository: str) -> dict:
    """Tag a local image as <registry>/<repository>:<tag> and push it; returns the pushed name and digest."""
    target = f"{registry}/{repository}:{image.rsplit(':', 1)[-1] if ':' in image else 'latest'}"
    code, out = await _docker("tag", image, target, timeout=60)
    if code == 0:
        code, out = await _docker("push", target, timeout=1200)
    digest = next((w for w in out.split() if w.startswith("sha256:")), "")
    return {"pushed": code == 0, "image": target, "digest": digest, "log": out[-3000:]}


async def remove_run_containers(run_key: str) -> list[str]:
    """Remove every container and network of one run (their names contain the run key) – used by Stop."""
    _, names = await _docker("ps", "-a", "--filter", f"name={run_key}", "--format", "{{.Names}}", timeout=30)
    names = names.split()
    if names:
        await _docker("rm", "-f", *names, timeout=120)
    _, nets = await _docker("network", "ls", "--filter", f"name={run_key}", "--format", "{{.Name}}", timeout=30)
    for net in nets.split():
        await _docker("network", "rm", net, timeout=30)
    return names


async def running_apps() -> dict[str, list[str]]:
    """Running containers → their published URLs ({name: ["http://127.0.0.1:32772", …]}); {} when Docker is down."""
    code, out = await _docker("ps", "--format", "{{.Names}}\t{{.Ports}}", timeout=20)
    if code != 0:
        return {}
    apps = {}
    for line in out.splitlines():
        name, _, ports = line.partition("\t")
        hosts = [p.split("->")[0] for p in ports.split(", ") if "->" in p and not p.startswith(":")]   # skip the IPv6 copies
        apps[name] = sorted({"http://" + h.replace("0.0.0.0", "localhost") for h in hosts})
    return apps


DOCKER_OPS = {"docker_status": docker_status, "docker_build": docker_build, "docker_run": docker_run,
              "docker_remove": docker_remove, "docker_registry": docker_registry, "docker_push": docker_push}
