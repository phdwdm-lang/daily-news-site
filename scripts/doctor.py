#!/usr/bin/env python3
"""Inspect local prerequisites; never install software, publish, or schedule work."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

CORE = ("daily_site.py", "workflow.py", "prepare_audit.py", "run_audit.py", "assets.py", "render_issue.py", "personal_renderer.py", "context_profile.py")
NETWORK = (
    ("rundown", "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml"),
    ("tldr", "https://tldr.tech/ai/archives"),
    ("superhuman", "https://www.superhuman.ai/"),
    ("builders-x", "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"),
    ("builders-podcasts", "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json"),
    ("builders-blogs", "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json"),
)


def command_output(command: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or result.stderr).strip()[:500]
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__


def filesystem_probe(parent: Path) -> dict:
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    try:
        import fcntl
        with tempfile.TemporaryDirectory(prefix=".daily-news-doctor-", dir=parent) as scratch:
            root = Path(scratch)
            old = root / "old"
            old.mkdir()
            (root / "current").symlink_to("old", target_is_directory=True)
            (root / "next").symlink_to("old", target_is_directory=True)
            os.replace(root / "next", root / "current")
            with (root / "lock").open("w") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with (root / "lock").open("w") as competing:
                    try:
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        raise OSError("exclusive filesystem locking is unavailable")
                fcntl.flock(handle, fcntl.LOCK_UN)
            descriptor = os.open(root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return {"status": "ok", "detail": "write, Unix exclusive lock, symbolic-link replace and directory fsync passed"}
    except (OSError, ImportError) as exc:
        return {"status": "error", "detail": "Workspace filesystem lacks required write/lock/symlink/fsync support: " + str(exc)}


def network_probe(source: tuple[str, str]) -> dict:
    name, url = source
    script = "const u=process.argv[1];try{const r=await fetch(u,{signal:AbortSignal.timeout(8000),redirect:'follow'});await r.body?.cancel();console.log(JSON.stringify({http_status:r.status,ok:r.ok}));}catch(e){console.log(JSON.stringify({ok:false,error:e.cause?.code||e.name}));}"
    code, output = command_output(["node", "--input-type=module", "-e", script, url])
    try:
        result = json.loads(output)
    except ValueError:
        result = {"ok": False, "error": "Node network probe failed"}
    return {"source": name, "url": url, "status": "ok" if code == 0 and result.get("ok") else "warning", **result}


def diagnose(project: Path | None = None, *, network: bool = False, ego_command: str = "ego-browser") -> dict:
    package = Path(__file__).resolve().parents[1]
    if project is None and (package / "scripts/daily_site.py").is_file():
        project = package
    template = (project.expanduser().resolve() if project else package / "assets/project-template")
    checks = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    system = platform.system()
    add("platform", "ok" if system == "Darwin" else "error" if system == "Windows" else "warning",
        "macOS is the validated first-release platform." if system == "Darwin" else
        "Native Windows is unsupported (Unix locks and symlinks required)." if system == "Windows" else
        "Unix may work, but this release has not completed Linux/WSL browser acceptance.")
    add("python", "ok" if sys.version_info >= (3, 11) else "error", platform.python_version() + "; supported release requires Python >=3.11")
    code, version = command_output(["node", "--version"])
    try:
        node_major = int(version.lstrip("v").split(".")[0])
    except ValueError:
        node_major = 0
    add("node", "ok" if code == 0 and node_major >= 18 else "error", version or "Node.js >=18 is required")
    code, curl = command_output(["curl", "--version"])
    add("curl", "ok" if code == 0 else "error", curl.splitlines()[0] if curl else "curl is required for selected image downloads")
    missing = [name for name in CORE if not (template / "scripts" / name).is_file()]
    add("template", "error" if missing else "ok", "Missing core files: " + ", ".join(missing) if missing else "Complete project runtime present")
    vendor = template / "resources/vendor/alpine.min.js"
    add("vendor", "ok" if vendor.is_file() and vendor.stat().st_size > 1000 else "error", "Bundled Alpine is required for the page controls")
    fs = filesystem_probe(template if template.exists() else template.parent)
    add("filesystem", fs["status"], fs["detail"])
    if project:
        config_file = template / ".daily-news/config.json"
        if not config_file.is_file():
            add("configuration", "error", "Workspace is not initialized: .daily-news/config.json is missing")
        else:
            try:
                module_path = template / "scripts/context_profile.py"
                if str(module_path.parent) not in sys.path:
                    sys.path.insert(0, str(module_path.parent))
                spec = importlib.util.spec_from_file_location("daily_news_context_doctor", module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                config = module.load_config(template)
                add("configuration", "ok", "Validated workspace configuration; context mode: " + config["context"]["mode"])
                if config["context"]["mode"] in ("profile", "context"):
                    profile_path = Path(config["context"].get("profile_path", ".daily-news/profile.json"))
                    profile_path = (profile_path if profile_path.is_absolute() else template / profile_path).resolve()
                    if not profile_path.is_relative_to((template / ".daily-news").resolve()):
                        raise ValueError("Private profile must stay inside the workspace .daily-news directory")
                    if profile_path.exists():
                        profile = module.validate_profile(json.loads(profile_path.read_text(encoding="utf-8")))
                        add("profile", "ok", str(len(profile["facts"])) + " confirmed facts validated; private text is not printed")
                    else:
                        add("profile", "ok", "No confirmed profile facts yet; empty personalization is supported")
            except (OSError, ValueError, KeyError, ImportError, AttributeError) as exc:
                add("configuration", "error", "Configuration validation failed: " + str(exc))
    ego = shutil.which(ego_command)
    if ego:
        code, output = command_output([ego, "nodejs", "-e", 'console.log(JSON.stringify({taskSpace:typeof taskSpace==="function"}))'])
        runtime_ready = code == 0 and '"taskSpace":true' in output.replace(" ", "")
        add("ego_runtime", "ok" if runtime_ready else "warning", "Ego command runtime exposes taskSpace; actual browser connection must be checked during candidate review." if runtime_ready else "Ego executable exists but its browser runtime was not confirmed (exit code " + str(code) + "). Check app connection and host/sandbox permissions; actual candidate review is still required.")
    else:
        add("ego_runtime", "warning", "Ego browser command was not found; install/connect it before candidate sign-off, or use the host's supported Ego tool.")
    add("host_visual_tools", "manual", "Agent host must expose image viewing and a connected Ego browser. CLI checks cannot prove visual understanding or actual browser review; publishing still requires real candidate checks and screenshots.")
    sources = []
    if network and node_major >= 18:
        with ThreadPoolExecutor(max_workers=4) as pool:
            sources = list(pool.map(network_probe, NETWORK))
    if network:
        successful = sum(row["status"] == "ok" for row in sources)
        add("network", "ok" if successful == len(NETWORK) else "warning" if successful else "error", f"{successful}/{len(NETWORK)} public source endpoints reachable via Node fetch; HTTP reachability does not prove article completeness. Historical replay additionally needs api.github.com.")
    else:
        add("network", "unchecked", "Use --network to test the six public source endpoints with Node fetch.")
    status = "blocked" if any(row["status"] == "error" for row in checks) else "needs_host_confirmation"
    return {"status": status, "checks": checks, "sources": sources,
            "browser_review_verified": False, "changes": "temporary filesystem probe only; no installation, hosting or scheduling"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--ego-command", default="ego-browser", help="executable name/path, not a shell command")
    args = parser.parse_args()
    try:
        result = diagnose(args.project, network=args.network, ego_command=args.ego_command)
    except (OSError, ValueError) as exc:
        result = {"status": "blocked", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
