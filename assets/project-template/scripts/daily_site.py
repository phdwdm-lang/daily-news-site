#!/usr/bin/env python3
"""Validate and atomically publish a dated, offline daily briefing.

Nothing in this module fetches sources, changes a scheduler, or deploys a site.
Serve ``SITE_ROOT/current`` so each request sees a complete generation.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import date, datetime, time, timezone, timedelta
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS_ROOT = PROJECT_ROOT / "resources"
DEFAULT_SITE_ROOT = PROJECT_ROOT / "site"
ISSUE_ZONE = timezone(timedelta(hours=8))


class ValidationError(ValueError):
    """A briefing cannot safely be published."""


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def obj(value: Any, context: str) -> dict:
    require(isinstance(value, dict), f"{context} 必须是对象")
    return value


def array(value: Any, context: str) -> list:
    require(isinstance(value, list), f"{context} 必须是数组")
    return value


def string(value: Any, context: str, *, blank: bool = False) -> str:
    require(isinstance(value, str), f"{context} 必须是字符串")
    require(blank or bool(value.strip()), f"{context} 不能为空")
    return value


def issue_date(value: Any) -> date:
    string(value, "date")
    require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "date 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("date 不是有效日期") from exc


def source_url(value: Any, context: str) -> str:
    value = string(value, context)
    require(not any(ord(c) < 32 or c.isspace() for c in value), f"{context} 含空白或控制字符")
    try:
        parts = urlsplit(value)
        require(parts.scheme in ("http", "https") and bool(parts.hostname),
                f"{context} 只接受完整 http/https 来源")
        require(parts.username is None and parts.password is None,
                f"{context} 不接受带凭据的来源")
        _ = parts.port
    except ValueError as exc:
        raise ValidationError(f"{context} 来源地址无效") from exc
    return value


def local_asset(value: Any, root: Path, context: str) -> tuple[str, Path]:
    value = string(value, context)
    require(not any(c in value for c in ("\\", "?", "#", "\x00", "%")),
            f"{context} 必须是普通 assets/ 相对路径")
    path = PurePosixPath(value)
    require(not path.is_absolute() and len(path.parts) > 1 and path.parts[0] == "assets"
            and all(p not in (".", "..", "") for p in value.split("/")),
            f"{context} 必须位于 assets/ 下，不能越过目录")
    resolved_root = root.resolve()
    resolved = (root / value).resolve()
    require(resolved.is_relative_to(resolved_root / "assets"), f"{context} 素材不能经符号链接越过 assets/")
    require(resolved.is_file(), f"{context} 缺少素材：{value}")
    return value, resolved


def image_size(path: Path) -> tuple[int, int]:
    """Read PNG/JPEG/WebP/SVG dimensions without optional libraries."""
    data = path.read_bytes()
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            require(len(data) >= 33 and data[12:16] == b"IHDR", f"PNG 头损坏：{path.name}")
            size = struct.unpack(">II", data[16:24])
        elif data.startswith(b"\xff\xd8"):
            at = 2
            size = None
            while at < len(data):
                require(data[at] == 0xFF, f"JPEG 标记损坏：{path.name}")
                while at < len(data) and data[at] == 0xFF:
                    at += 1
                marker = data[at]
                at += 1
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                require(at + 2 <= len(data), f"JPEG 头截断：{path.name}")
                length = int.from_bytes(data[at:at + 2], "big")
                require(length >= 2 and at + length <= len(data), f"JPEG 段截断：{path.name}")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    require(length >= 7, f"JPEG 尺寸损坏：{path.name}")
                    height, width = struct.unpack(">HH", data[at + 3:at + 7])
                    size = (width, height)
                    break
                require(marker != 0xDA, f"JPEG 缺少尺寸：{path.name}")
                at += length
            require(size is not None, f"JPEG 缺少尺寸：{path.name}")
        elif len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                size = (1 + int.from_bytes(data[24:27], "little"),
                        1 + int.from_bytes(data[27:30], "little"))
            elif chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
                width, height = struct.unpack("<HH", data[26:30])
                size = (width & 0x3FFF, height & 0x3FFF)
            elif chunk == b"VP8L" and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                size = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            else:
                raise ValidationError(f"不支持的 WebP 头：{path.name}")
        elif path.suffix.lower() == ".svg":
            require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(),
                    f"SVG 不允许外部实体：{path.name}")
            root = ET.fromstring(data)
            require(root.tag.split("}")[-1] == "svg", f"不是 SVG：{path.name}")
            width = re.fullmatch(r"([\d.]+)(?:px)?", root.get("width", ""))
            height = re.fullmatch(r"([\d.]+)(?:px)?", root.get("height", ""))
            if width and height:
                size = (round(float(width[1])), round(float(height[1])))
            else:
                viewbox = re.split(r"[\s,]+", root.get("viewBox", "").strip())
                require(len(viewbox) == 4, f"SVG 缺少尺寸或 viewBox：{path.name}")
                size = (round(float(viewbox[2])), round(float(viewbox[3])))
        else:
            raise ValidationError(f"素材不是支持的 PNG/JPEG/WebP/SVG：{path.name}")
        require(all(isinstance(n, int) and n > 0 for n in size), f"图片尺寸无效：{path.name}")
        return size
    except (IndexError, struct.error, ET.ParseError, OverflowError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"图片头损坏：{path.name}") from exc


def publication(value: Any, day: date, context: str) -> None:
    if value is None:
        return
    value = obj(value, context)
    posts = value.get("posts")
    records = array(posts, context + ".posts") if posts is not None else [value]
    require(bool(records), context + " 必须有真实发表时间")
    cutoff = datetime.combine(day + timedelta(days=1), time.min, ISSUE_ZONE)
    for index, record in enumerate(records):
        record = obj(record, f"{context}[{index}]")
        stamp = string(record.get("published_at"), context + ".published_at")
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(context + " 发表时间无效") from exc
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                context + " 发表时间必须带时区")
        require(parsed < cutoff, context + " 发表时间晚于简报当天结束")
        if "url" in record:
            source_url(record["url"], context + ".url")


def validate_issue(issue: Any, assets_root: Path = DEFAULT_ASSETS_ROOT) -> dict[str, Path]:
    issue = obj(issue, "issue")
    require(type(issue.get("schema_version")) is int and issue["schema_version"] == 1,
            "schema_version 必须是整数 1")
    day = issue_date(issue.get("date"))
    product = obj(issue.get("product"), "product")
    assets: dict[str, Path] = {}
    populated = False
    product_sources: set[tuple[str, str]] = set()
    require(len(product.get("featured", [])) <= 4, "本期重点最多四条，不凑数")

    def image(value: Any, context: str) -> None:
        if value is None:
            return
        value = obj(value, context)
        name, path = local_asset(value.get("path"), assets_root, context + ".path")
        string(value.get("caption"), context + ".caption", blank=True)
        string(value.get("kind"), context + ".kind", blank=True)
        for key in ("width", "height"):
            require(type(value.get(key)) is int and value[key] > 0,
                    context + f".{key} 必须是正整数")
        require(image_size(path) == (value["width"], value["height"]),
                context + " 声明尺寸与实际图片不一致")
        if "focus" in value:
            require(value["focus"] == "muse", context + ".focus 仅接受 muse")
        assets[name] = path

    def links(value: Any, context: str) -> None:
        items = array(value, context)
        require(bool(items), context + " 至少需要一个来源")
        for item in items:
            item = obj(item, context + "[]")
            string(item.get("text"), context + ".text")
            source_url(item.get("url"), context + ".url")

    def paragraphs(value: Any, context: str) -> None:
        rows = array(value, context)
        require(bool(rows), context + " 不能为空")
        for paragraph in rows:
            string(paragraph, context + "[]")

    for category in ("featured", "personal", "quick", "unselected"):
        items = array(product.get(category), "product." + category)
        populated = populated or bool(items)
        for index, item in enumerate(items):
            context = f"product.{category}[{index}]"
            item = obj(item, context)
            for key in ("title", "label", "core"):
                string(item.get(key), context + "." + key)
            item_source = source_url(item.get("url"), context + ".url")
            normalized_source = (item_source.rstrip("/"), item["title"].strip())
            require(normalized_source not in product_sources, context + " 与其他栏目完全重复；同一资讯只能属于一个栏目")
            product_sources.add(normalized_source)
            if category == "featured":
                display = obj(item.get("display"), context + ".display")
                points = array(display.get("points"), context + ".display.points")
                require(bool(points), context + ".display.points 不能为空")
                for point in points:
                    require(isinstance(point, list) and len(point) == 2,
                            context + ".display.points 每项必须为两个字符串")
                    for part in point:
                        string(part, context + ".display.points[]", blank=True)
                string(display.get("judgment"), context + ".display.judgment")
                require("image" in item, context + ".image 必须是图片对象或 null")
                image(item["image"], context + ".image")
            elif category == "personal":
                tags = item.get("tags", "")
                require(isinstance(tags, str) or (isinstance(tags, list) and all(isinstance(tag,str) for tag in tags)), context + ".tags 必须是字符串或字符串数组")
                string(item.get("relation"), context + ".relation")
                string(item.get("question", ""), context + ".question", blank=True)
                require("image" in item, context + ".image 必须是图片对象或 null")
                image(item["image"], context + ".image")
    builders = array(issue.get("builders"), "builders")
    populated = populated or bool(builders)
    authors: set[str] = set()
    for index, builder in enumerate(builders):
        context = f"builders[{index}]"
        builder = obj(builder, context)
        for key in ("author", "role", "one_sentence"):
            string(builder.get(key), context + "." + key, blank=(key == "role"))
        require(builder["author"] not in authors, context + " 作者重复；请汇总其当天内容")
        authors.add(builder["author"])
        paragraphs(builder.get("paragraphs"), context + ".paragraphs")
        links(builder.get("links"), context + ".links")
        require("avatar" in builder, context + ".avatar 必须是头像路径或 null")
        if builder["avatar"] is not None:
            name, path = local_asset(builder["avatar"], assets_root, context + ".avatar")
            image_size(path)
            assets[name] = path
        require("publication" in builder, context + ".publication 必须是时间对象或 null")
        publication(builder["publication"], day, context + ".publication")
    podcast = issue.get("podcast")
    require("podcast" in issue, "podcast 必须是对象或 null")
    if podcast is not None:
        podcast = obj(podcast, "podcast")
        populated = True
        for key in ("title", "title_zh", "series", "lead"):
            string(podcast.get(key), "podcast." + key)
        paragraphs(podcast.get("paragraphs"), "podcast.paragraphs")
        links(podcast.get("links"), "podcast.links")
        require("publication" in podcast, "podcast.publication 必须是时间对象或 null")
        publication(podcast["publication"], day, "podcast.publication")
    if "source_note" in issue:
        string(issue["source_note"], "source_note", blank=True)
    require(populated, "整期内容为空，拒绝替换当前网站")
    return assets


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"无法读取有效 JSON：{path}") from exc


def load_renderer():
    renderer = PROJECT_ROOT / "scripts" / "render_issue.py"
    if str(renderer.parent) not in sys.path:
        sys.path.insert(0, str(renderer.parent))
    require(renderer.is_file(), "缺少 scripts/render_issue.py，尚不能发布")
    spec = importlib.util.spec_from_file_location("daily_site_renderer", renderer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_issue


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def site_lock(site_root: Path):
    site_root.mkdir(parents=True, exist_ok=True)
    with (site_root / ".publish.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValidationError("另一个更新正在提交，请稍后重试") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def active_release(site_root: Path) -> Path | None:
    current = site_root / "current"
    if not current.is_symlink():
        require(not current.exists(), "current 已是普通文件或目录，拒绝覆盖")
        return None
    release = current.resolve()
    require(release.is_relative_to((site_root / "releases").resolve())
            and (release / "manifest.json").is_file(), "current 指向无效快照")
    return release


def switch_release(site_root: Path, release: Path) -> None:
    target = os.path.relpath(release, site_root)
    temporary = site_root / (".current-" + next(tempfile._get_candidate_names()))
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, site_root / "current")
        fsync_directory(site_root)
    finally:
        temporary.unlink(missing_ok=True)


def append_event(site_root: Path, event: dict) -> str | None:
    """A failed secondary log must not misreport a committed generation as failed."""
    event = {"at": datetime.now(timezone.utc).isoformat(), **event}
    try:
        with (site_root / "events.jsonl").open("ab") as handle:
            handle.write(canonical(event))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        return f"网站已切换，但附加日志写入失败：{exc.strerror}；快照 manifest 已保留提交信息"
    return None


def namespaced(issue: dict) -> dict:
    rendered = copy.deepcopy(issue)
    for category in ("featured", "personal"):
        for item in rendered["product"][category]:
            if item["image"] is not None:
                item["image"]["path"] = f"assets/{issue['date']}/" + item["image"]["path"][7:]
    for builder in rendered["builders"]:
        if builder["avatar"] is not None:
            builder["avatar"] = f"assets/{issue['date']}/" + builder["avatar"][7:]
    return rendered


def publish(issue: dict, site_root: Path = DEFAULT_SITE_ROOT,
            assets_root: Path = DEFAULT_ASSETS_ROOT, *, replace: bool = False,
            preview_root: Path | None = None) -> dict:
    assets = validate_issue(issue, assets_root)
    asset_hashes = {name: sha256(path.read_bytes()) for name, path in sorted(assets.items())}
    issue_hash = sha256(canonical({"issue": issue, "assets": asset_hashes}))
    day = issue["date"]
    site_root = site_root.resolve()
    with site_lock(site_root):
        previous = active_release(site_root)
        previous_manifest = load_json(previous / "manifest.json") if previous else {"issues": {}}
        records = copy.deepcopy(previous_manifest["issues"])
        existing = records.get(day)
        template_files = [PROJECT_ROOT / "scripts" / name for name in ("render_issue.py", "personal_renderer.py")]
        renderer_hash = sha256(b"".join(path.read_bytes() for path in template_files if path.exists()))
        if existing and existing["sha256"] == issue_hash and previous_manifest.get("renderer_sha256") == renderer_hash and preview_root is None:
            return {"status": "unchanged", "date": day, "latest": previous_manifest["latest"],
                    "release": previous.name, "entry": str(site_root / "current" / "index.html")}
        require(not existing or existing["sha256"] == issue_hash or replace or preview_root is not None,
                f"{day} 已存在不同内容；需明确使用 --replace 才能更正，旧快照仍会保留")
        renderer = load_renderer()
        records[day] = {"sha256": issue_hash, "html": f"issues/{day}.html",
                        "json": f"issues/{day}.json", "assets": asset_hashes}
        dates = sorted(records, reverse=True)
        generation = sha256(canonical({"issues": records, "renderer": renderer_hash}))[:24]
        releases = preview_root.resolve() if preview_root is not None else site_root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        final = releases / generation
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
        try:
            if previous and (previous / "assets").exists():
                shutil.copytree(previous / "assets", stage / "assets")
            for name, source in assets.items():
                destination = stage / "assets" / day / name[7:]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                require(sha256(destination.read_bytes()) == asset_hashes[name],
                        f"素材在验证后改变，取消发布：{name}")
            vendor = assets_root / "vendor"
            if vendor.is_dir():
                shutil.copytree(vendor, stage / "vendor", symlinks=False)
            elif previous and (previous / "vendor").is_dir():
                shutil.copytree(previous / "vendor", stage / "vendor")
            require((stage / "vendor" / "alpine.min.js").is_file(), "缺少定稿页面运行所需 vendor/alpine.min.js")
            for archived_day, record in records.items():
                for asset_name, digest in record["assets"].items():
                    saved_asset = stage / "assets" / archived_day / asset_name[7:]
                    require(saved_asset.is_file() and sha256(saved_asset.read_bytes()) == digest, f"历史素材缺失或改变：{archived_day}/{asset_name}")
            issues: dict[str, dict] = {}
            for archived_day in dates:
                archived = issue if archived_day == day else load_json(previous / records[archived_day]["json"])
                issues[archived_day] = archived
                write_file(stage / records[archived_day]["json"], canonical(archived))
                html = renderer(namespaced(archived), dates, asset_prefix="../", issue_href_prefix="")
                require(isinstance(html, str) and bool(html.strip()), "渲染器返回空页面")
                write_file(stage / records[archived_day]["html"], html.encode("utf-8"))
            html = renderer(namespaced(issues[dates[0]]), dates, asset_prefix="", issue_href_prefix="issues/")
            require(isinstance(html, str) and bool(html.strip()), "渲染器返回空首页")
            write_file(stage / "index.html", html.encode("utf-8"))
            manifest = {"schema_version": 1, "generation": generation,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "renderer_sha256": renderer_hash, "latest": dates[0], "dates": dates, "issues": records,
                        "previous_generation": previous.name if previous else None,
                        "operation": "replace" if existing else "publish", "updated_date": day}
            write_file(stage / "manifest.json", canonical(manifest))
            fsync_directory(stage)
            if final.exists():
                require(load_json(final / "manifest.json")["issues"] == records,
                        "快照标识冲突，取消提交")
                shutil.rmtree(stage)
            else:
                os.replace(stage, final)
                fsync_directory(releases)
            if preview_root is not None:
                return {"status": "preview", "date": day, "latest": dates[0],
                        "release": generation, "preview_path": str(final),
                        "entry": str(final / "index.html")}
            switch_release(site_root, final)
            warning = append_event(site_root, {"action": manifest["operation"], "date": day,
                                              "from": previous.name if previous else None,
                                              "to": generation, "latest": dates[0]})
            result = {"status": "published", "date": day, "latest": dates[0],
                      "release": generation, "entry": str(site_root / "current" / "index.html")}
            if warning:
                result["warning"] = warning
            return result
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def status(site_root: Path = DEFAULT_SITE_ROOT) -> dict:
    site_root = site_root.resolve()
    current = active_release(site_root)
    if current is None:
        return {"status": "empty", "site_root": str(site_root)}
    manifest = load_json(current / "manifest.json")
    return {"status": "ready", "latest": manifest["latest"], "dates": manifest["dates"],
            "release": current.name, "entry": str(site_root / "current" / "index.html")}


def rollback(day: str | None, site_root: Path = DEFAULT_SITE_ROOT, *, release_id: str | None = None) -> dict:
    if day is not None:
        issue_date(day)
    require(day is not None or release_id is not None, "回滚需要日期或 --release")
    if release_id is not None:
        require(bool(re.fullmatch(r"[0-9a-f]{24}", release_id)), "--release 不是有效快照标识")
    site_root = site_root.resolve()
    with site_lock(site_root):
        previous = active_release(site_root)
        require(previous is not None, "网站尚无可回滚快照")
        choices: list[tuple[str, Path, dict]] = []
        for manifest_path in (site_root / "releases").glob("*/manifest.json"):
            candidate = manifest_path.parent
            if candidate.name.startswith("."):
                continue
            manifest = load_json(manifest_path)
            if ((release_id is not None and candidate.name == release_id)
                    or (release_id is None and manifest.get("latest") == day)):
                choices.append((manifest["created_at"], candidate, manifest))
        require(bool(choices), "没有符合条件的已完成快照；请先用 status 查看当前日期，并保留原站点")
        _, target, manifest = max(choices, key=lambda item: item[0])
        require((target / "index.html").is_file(), "回滚快照缺少首页，取消切换")
        switch_release(site_root, target)
        warning = append_event(site_root, {"action": "rollback", "date": manifest["latest"],
                                          "from": previous.name, "to": target.name})
        result = {"status": "rolled_back", "latest": manifest["latest"], "release": target.name,
                  "entry": str(site_root / "current" / "index.html")}
        if warning:
            result["warning"] = warning
        return result


def main(argv: list[str] | None = None, *, audit_runs_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "publish"):
        child = sub.add_parser(name)
        child.add_argument("issue_json", type=Path)
        child.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
        child.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT,
                           help="包含 assets/ 和可选 vendor/ 的素材根目录")
        child.add_argument("--audit", type=Path, required=(name == "publish"),
                           help="本次 data/runs 内的来源审计；发布必须包含匹配候选的 Ego 签收")
        if name == "validate":
            child.add_argument("--preview-root", type=Path,
                               help="生成完整候选目录，但不切换当前站点")
        if name == "publish":
            child.add_argument("--replace", action="store_true")
    child = sub.add_parser("status")
    child.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
    child = sub.add_parser("rollback")
    child.add_argument("date", nargs="?")
    child.add_argument("--release", dest="release_id")
    child.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            issue = load_json(args.issue_json)
            assets = validate_issue(issue, args.assets_root)
            if args.audit is not None:
                from run_audit import validate_run_audit
                validate_run_audit(issue, args.audit, args.assets_root,
                                   runs_root=audit_runs_root or PROJECT_ROOT / "data" / "runs")
            result = (publish(issue, args.site_root, args.assets_root, preview_root=args.preview_root)
                      if args.preview_root is not None else
                      {"status": "valid", "date": issue["date"], "assets": len(assets)})
        elif args.command == "publish":
            from run_audit import validate_run_audit
            issue = load_json(args.issue_json)
            validate_run_audit(issue, args.audit, args.assets_root,
                               runs_root=audit_runs_root or PROJECT_ROOT / "data" / "runs", require_qa=True)
            result = publish(issue, args.site_root, args.assets_root, replace=args.replace)
        elif args.command == "status":
            result = status(args.site_root)
        else:
            result = rollback(args.date, args.site_root, release_id=args.release_id)
    except (ValidationError, OSError, ImportError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
