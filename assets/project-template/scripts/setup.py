#!/usr/bin/env python3
"""Create a new private daily-news-site workspace from the bundled clean template."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
MARKER = ".daily-news/install.json"
RUNTIME_FILES = ("collect.mjs", "builders-source.mjs", "products-source.mjs", "setup.py", "doctor.py")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "SKILL.md").is_file():
        raise ValueError("Run setup.py from the downloaded or installed daily-news-site Skill folder.")
    return root


def initialize(workspace: Path, *, package: Path | None = None) -> dict:
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11 or newer is required for this supported release.")
    timezone_name = "Asia/Shanghai"
    theme = "light"
    ZoneInfo(timezone_name)
    target = workspace.expanduser().absolute()
    if target.is_symlink():
        raise ValueError("Workspace must be a new directory, not a symbolic link.")
    if target.exists():
        marker = target / MARKER
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("The selected directory already exists; choose a new workspace. Nothing was overwritten.") from None
        if saved.get("application") != "daily-news-site" or saved.get("schema_version") != 1:
            raise ValueError("Existing directory is not a supported initialized workspace. Nothing was overwritten.")
        required = (".daily-news/config.json", ".daily-news/profile.json", "scripts/daily_site.py", "resources/vendor/alpine.min.js")
        if not all((target / name).is_file() for name in required):
            raise ValueError("Existing workspace is incomplete; setup will not repair or overwrite it automatically.")
        return {"status": "unchanged", "workspace": str(target), "message": "Existing workspace preserved, including all preferences and personal context."}
    source = (package or package_root()).resolve()
    template = source / "assets/project-template"
    if not template.is_dir() or not (source / "SKILL.md").is_file():
        raise ValueError("Clean project template is missing. Use the complete release, not only SKILL.md.")
    for name in ("scripts/daily_site.py", "resources/vendor/alpine.min.js"):
        if not (template / name).is_file():
            raise ValueError("Project template is incomplete: " + name)
    if any(path.is_symlink() for path in template.rglob("*")):
        raise ValueError("Project template must not contain symbolic links.")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".daily-news-setup-", dir=target.parent))
    try:
        shutil.copytree(template, stage, dirs_exist_ok=True)
        bundled = stage / "skills/daily-news-site"
        bundled.mkdir(parents=True)
        shutil.copy2(source / "SKILL.md", bundled / "SKILL.md")
        for directory in ("agents", "references", "resources", "licenses"):
            if (source / directory).is_dir():
                shutil.copytree(source / directory, bundled / directory)
        (bundled / "scripts").mkdir()
        for name in RUNTIME_FILES:
            if not (source / "scripts" / name).is_file():
                raise ValueError("Incomplete Skill release: scripts/" + name)
            shutil.copy2(source / "scripts" / name, bundled / "scripts" / name)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            if (source / name).is_file():
                shutil.copy2(source / name, bundled / name)
        for directory in ("data/issues", "data/runs", "site", "resources/assets/cache"):
            (stage / directory).mkdir(parents=True, exist_ok=True)
        write_json(stage / ".daily-news/config.json", {
            "schema_version": 1, "context": {"mode": "none", "profile_path": ".daily-news/profile.json", "sources": [], "fallback": "error"},
            "timezone": timezone_name, "theme": theme,
        })
        write_json(stage / ".daily-news/profile.json", {"schema_version": 1, "facts": []})
        write_json(stage / MARKER, {"schema_version": 1, "application": "daily-news-site", "version": VERSION,
                                  "initialized_at": datetime.now(timezone.utc).isoformat()})
        os.chmod(stage / ".daily-news", 0o700)
        for path in (stage / ".daily-news").iterdir():
            if path.is_file():
                os.chmod(path, 0o600)
        # mkdir reserves a nonexistent target atomically. A competing setup or
        # an unrelated empty directory must never be replaced by a plain rename.
        target.mkdir()
        try:
            stage.rename(target)
        except OSError:
            # Only remove our own empty reservation; preserve unexpected files.
            try:
                target.rmdir()
            except OSError:
                pass
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"status": "initialized", "workspace": str(target), "context_mode": "none", "theme": theme,
            "next": "Run scripts/doctor.py --project WORKSPACE; then ask the agent to update today's briefing."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="new directory chosen by the user")
    args = parser.parse_args()
    try:
        result = initialize(args.workspace)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
