#!/usr/bin/env python3
"""Local input provenance and review gate for the daily briefing.

Checks bind a review record to source bytes, selected data, cached media and the
exact candidate files. A recorded Ego sign-off is traceable human/agent review;
its presence is not a technical proof that somebody actually used a browser.
No source text or embedded script is executed by this module.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import daily_site as site
import context_profile as context

DEFAULT_RUNS_ROOT = site.PROJECT_ROOT / "data" / "runs"


def timestamp(value: Any, label: str) -> datetime:
    site.string(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise site.ValidationError(label + " 不是有效时间") from exc
    site.require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                 label + " 必须带时区")
    return parsed


def _digest(value: Any, label: str) -> str:
    site.require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                 label + " 必须为 SHA-256")
    return value


def _file(record: Any, root: Path, label: str) -> Path:
    record = site.obj(record, label)
    raw = site.string(record.get("path"), label + ".path")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    site.require(path.is_relative_to(root.resolve()) and path.is_file(),
                 label + " 必须是本项目 data/runs 内的已保存文件")
    site.require(site.sha256(path.read_bytes()) == _digest(record.get("sha256"), label + ".sha256"),
                 label + " 文件与采集记录摘要不一致")
    return path


def parse_tasks(source: str) -> list[dict]:
    """Read one strict JSON array after ``const tasks =``; never eval JavaScript."""
    starts = list(re.finditer(r"\bconst\s+tasks\s*=\s*", source))
    site.require(len(starts) == 1, "待办源文件必须含唯一的 const tasks JSON 数组")
    try:
        tasks, end = json.JSONDecoder().raw_decode(source[starts[0].end():])
    except json.JSONDecodeError as exc:
        raise site.ValidationError("待办 tasks 不是可安全读取的 JSON 数组") from exc
    tail = source[starts[0].end() + end:].lstrip()
    site.require(not tail or tail.startswith(";"), "待办 tasks 后存在非声明内容")
    tasks = site.array(tasks, "待办 tasks")
    ids = []
    for task in tasks:
        task = site.obj(task, "待办 task")
        ids.append(site.string(task.get("id"), "待办 task.id"))
    site.require(len(ids) == len(set(ids)), "待办任务 ID 重复")
    return tasks


def _contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, list):
        return any(_contains(part, needle) for part in value)
    if isinstance(value, dict):
        return any(_contains(part, needle) for part in value.values())
    return False


def validate_builders(issue: dict, raw: dict) -> dict:
    # Ancillary podcast/blog failures must not discard a complete X branch.
    # A partial response needs explicit X success; absent evidence fails closed.
    feed_status = raw.get("feedStatus", {})
    x_status = feed_status.get("x", {}) if isinstance(feed_status, dict) else {}
    x_succeeded = isinstance(x_status, dict) and x_status.get("status") == "ok"
    site.require(raw.get("status") == "ok" or (raw.get("status") == "partial" and x_succeeded),
                 "Builders 采集不是成功状态且缺少 X 完整成功证据，不能当作空结果")
    rows = site.array(raw.get("x"), "Builders raw.x")
    expected = {}
    for row in rows:
        row = site.obj(row, "Builders raw.x[]")
        name = site.string(row.get("name"), "Builders raw.name")
        site.require(name not in expected, "Builders 原始作者重复")
        tweets = site.array(row.get("tweets"), "Builders raw.tweets")
        site.require(bool(tweets), "Builders 作者没有可对应原帖；不能把部分错误当空成功")
        expected[name] = {}
        for tweet in tweets:
            tweet = site.obj(tweet, "Builders tweet")
            url = site.source_url(tweet.get("url"), "Builders tweet.url")
            site.require(url not in expected[name], "Builders 原始原帖重复")
            expected[name][url] = timestamp(tweet.get("createdAt"), "Builders tweet.createdAt")
    actual = {}
    for builder in site.array(issue.get("builders"), "issue.builders"):
        name = builder["author"]
        site.require(name not in actual, "Builders 页面作者重复")
        links = [row["url"] for row in builder["links"]]
        site.require(len(links) == len(set(links)), "Builders 页面原帖链接重复")
        publication = site.obj(builder.get("publication"), "Builders publication")
        posts = site.array(publication.get("posts"), "Builders publication.posts")
        records = {}
        for post in posts:
            url = site.source_url(post.get("url"), "Builders publication.url")
            site.require(url not in records, "Builders 页面时间记录重复")
            records[url] = timestamp(post.get("published_at"), "Builders publication.published_at")
        site.require(set(links) == set(records), "Builders 原帖与发布时间记录不对应")
        actual[name] = records
    site.require(set(actual) == set(expected), "Builders 作者集合与原始返回不一致；有漏人或增加人物")
    for name, records in expected.items():
        site.require(set(actual[name]) == set(records), f"Builders {name} 原帖集合与原始返回不一致")
        site.require(actual[name] == records, f"Builders {name} 原始发布时间不一致")
    stats = raw.get("stats", {})
    for key, value in (("xBuilders", len(expected)), ("totalTweets", sum(map(len, expected.values())))):
        if key in stats:
            site.require(stats[key] == value, "Builders 原始统计与实际内容不一致")
    return {"authors": len(expected), "posts": sum(map(len, expected.values()))}


def _todo(issue: dict, audit: dict, root: Path, started: datetime, run_id: str) -> dict:
    todo = site.obj(audit.get("todo"), "audit.todo")
    # v1 already records its selected Page and the byte hashes in its sign-off.
    # Read that identity instead of shipping one author's private Page constant.
    page_id = site.string(todo.get("page_id"), "todo.page_id")
    reference = site.string(todo.get("reference"), "todo.reference")
    read_at = timestamp(todo.get("read_at"), "todo.read_at")
    site.require(read_at >= started, "待办快照早于本次运行，必须重新读取")
    page = site.load_json(_file(todo.get("page"), root, "todo.page"))
    site.require(_contains(page, page_id), "本次待办页面记录缺少指定页面 ID")
    site.require(_contains(page, reference), "本次页面记录没有引用此待办源文件")
    source = _file(todo.get("source"), root, "todo.source")
    tasks = parse_tasks(source.read_text(encoding="utf-8"))
    record = site.load_json(_file(todo.get("record"), root, "todo.record"))
    site.require(record.get("run_id") == run_id and record.get("page_id") == page_id
                 and record.get("reference") == reference, "待办提取记录不属于本次输入")
    site.require(record.get("read_at") == todo["read_at"], "待办读取时间记录不一致")
    site.require(record.get("source_sha256") == todo["source"]["sha256"], "待办源文件摘要与提取记录不一致")
    site.require(record.get("tasks") == tasks, "待办提取内容不完整或与源文件不一致")
    ids = {task["id"] for task in tasks}
    bindings = site.array(audit.get("personal_bindings"), "personal_bindings")
    personal_urls = [row["url"] for row in issue["product"]["personal"]]
    mapped = {}
    for binding in bindings:
        url = site.source_url(binding.get("url"), "personal_bindings.url")
        site.require(url not in mapped, "个人关联来源重复绑定")
        selected = site.array(binding.get("task_ids"), "personal_bindings.task_ids")
        site.require(bool(selected) and len(selected) == len(set(selected)), "个人关联必须绑定明确任务 ID")
        site.require(all(isinstance(task_id, str) and task_id in ids for task_id in selected),
                     "个人关联绑定了不在当前待办源文件中的任务")
        mapped[url] = selected
    site.require(set(mapped) == set(personal_urls) and len(personal_urls) == len(set(personal_urls)),
                 "个人关联绑定必须逐条覆盖当前栏目")
    return {"tasks": len(tasks), "personal_items": len(mapped)}


def context_snapshot(snapshot_record: dict, root: Path, started: datetime, run_id: str) -> tuple[dict, list[Path]]:
    """Re-derive facts from immutable selected evidence and confirmed profiles."""
    path = _file(snapshot_record, root, "context.snapshot")
    site.require(path.name == "snapshot.json" and path.parent.name == "context", "个人参考必须使用本运行context/snapshot.json")
    owner = site.obj(site.load_json(path.parent.parent / "run.json"), "context.run.json")
    site.require(owner.get("id") == run_id and timestamp(owner.get("started_at"), "context.run.started_at") == started,
                 "个人参考快照目录不属于本次运行")
    snapshot = site.obj(site.load_json(path), "context snapshot")
    site.require(snapshot.get("schema_version") == 1 and snapshot.get("run_id") == run_id,
                 "个人参考快照不属于本次运行")
    captured = timestamp(snapshot.get("captured_at"), "context.captured_at")
    site.require(captured >= started, "个人参考读取早于本次运行")
    config_path = _file(snapshot.get("config"), path.parent, "context.config")
    config = context.validate_config(site.load_json(config_path))
    mode = config["context"]["mode"]
    site.require(snapshot.get("mode") == mode, "个人参考模式与本次配置不一致")
    paths = [path, config_path]
    expected = []
    profile_record = snapshot.get("profile")
    if profile_record is not None:
        site.require(mode in ("profile", "context"), "none 模式不能读取profile")
        profile_path = _file(profile_record, path.parent, "context.profile")
        paths.append(profile_path)
        profile = context.validate_profile(site.load_json(profile_path))
        for fact in profile["facts"]:
            site.require(timestamp(fact["confirmed_at"], "fact.confirmed_at") <= captured,
                         "个人事实确认晚于本次参考快照")
        expected.extend(profile["facts"])
    configured = {row["id"]: row for row in config["context"].get("sources", [])} if mode == "context" else {}
    recorded = {}
    for row in site.array(snapshot.get("sources"), "context.sources"):
        row = site.obj(row, "context.source")
        source_id = site.string(row.get("id"), "context.source.id")
        site.require(source_id in configured and source_id not in recorded, "个人来源未配置或重复")
        selected = configured[source_id]
        site.require(row.get("kind") == selected["kind"], "个人来源类型与选择不一致")
        data_path = _file(row.get("file"), path.parent, "context.source.file")
        paths.append(data_path)
        provenance = site.obj(row.get("provenance"), "context.source.provenance")
        read_at = timestamp(row.get("read_at"), "context.source.read_at")
        site.require(started <= read_at <= captured, "个人来源读取时间不属于本次运行")
        site.require(provenance.get("kind") == row["kind"] and provenance.get("read_at") == row["read_at"],
                     "个人来源读取记录不一致")
        original = site.string(row.get("original_path"), "context.source.original_path")
        site.require(provenance.get("reference") == selected.get("reference", original),
                     "个人来源引用与配置不一致")
        if selected.get("activity_at") is not None:
            site.require(provenance.get("activity_at") == selected["activity_at"], "个人来源活动时间与配置不一致")
        else:
            site.require("activity_at" not in provenance, "不能用读取或文件时间编造活动时间")
        if selected["kind"] == "page":
            site.require(row["read_at"] == selected["read_at"], "Page 读取时间与宿主证据不一致")
            text = data_path.read_text(encoding="utf-8")
            site.require(selected["page_id"] in text, "Page 证据不含所选 page_id")
            if selected.get("reference"):
                site.require(selected["reference"] in text, "Page 证据不含所选引用")
        expected.extend(context.source_facts(data_path.read_bytes(), row.get("suffix", ".json"), source_id, provenance))
        recorded[source_id] = row
    errors = site.array(snapshot.get("source_errors"), "context.source_errors")
    missing = set()
    for error in errors:
        error = site.obj(error, "context.source_error")
        source_id = error.get("id")
        site.require(source_id in configured and source_id not in recorded and source_id not in missing,
                     "个人来源失败记录未配置或重复")
        site.require(error.get("kind") == configured[source_id]["kind"] and error.get("status") == "unavailable",
                     "个人来源失败记录类型无效")
        site.string(error.get("error"), "context.source_error.error")
        missing.add(source_id)
    site.require(set(recorded) | missing == set(configured), "个人参考源未完整记录；不能把不可读冒充空结果")
    effective = config["context"].get("fallback", "error") if errors else mode
    site.require(effective in context.MODES and snapshot.get("effective_mode") == effective,
                 "个人参考降级没有显式配置或快照模式不一致")
    if mode == "context":
        site.require(bool(configured), "context 模式没有明确选择参考源")
    if effective == "none":
        expected = []
    elif effective == "profile":
        expected = [fact for fact in expected if fact["status"] == "confirmed"]
    site.require(snapshot.get("facts") == expected, "个人事实与完整来源/确认记录不一致；未确认候选不能作为依据")
    site.require(len({fact["id"] for fact in expected}) == len(expected), "个人参考事实 ID 重复")
    return snapshot, paths


def _context(issue: dict, audit: dict, root: Path, started: datetime, run_id: str) -> tuple[dict, list[Path]]:
    value = site.obj(audit.get("context"), "audit.context")
    snapshot, paths = context_snapshot(value.get("snapshot"), root, started, run_id)
    facts = {fact["id"]: fact for fact in snapshot["facts"]}
    mapped = {}
    for binding in site.array(audit.get("personal_bindings"), "personal_bindings"):
        binding = site.obj(binding, "personal_bindings[]")
        url = site.source_url(binding.get("url"), "personal_bindings.url")
        site.require(url not in mapped, "个人关联来源重复绑定")
        selected = site.array(binding.get("context_ids"), "personal_bindings.context_ids")
        site.require(bool(selected) and len(selected) == len(set(selected)), "个人关联必须绑定明确context_ids")
        site.require(all(isinstance(fact_id, str) and fact_id in facts for fact_id in selected),
                     "个人关联引用了当前快照以外或未确认的事实")
        if "fact_types" in binding:
            types = site.array(binding["fact_types"], "personal_bindings.fact_types")
            site.require(set(types) == {facts[fact_id]["type"] for fact_id in selected}, "个人关联事实类型与context_ids不一致")
        mapped[url] = selected
    urls = [row["url"] for row in issue["product"]["personal"]]
    site.require(set(mapped) == set(urls) and len(urls) == len(set(urls)), "个人关联绑定必须逐条覆盖当前栏目")
    return {"mode": snapshot["effective_mode"], "facts": len(facts), "personal_items": len(mapped),
            "source_errors": snapshot["source_errors"]}, paths


def source_hashes(audit: dict) -> dict:
    """Bind the full media decisions, including all evidence hashes, to sign-off."""
    personal = ({"context": audit["context"]["snapshot"]["sha256"]} if audit.get("schema_version") == 2 else
                {"todo_" + key: audit["todo"][key]["sha256"] for key in ("page", "source", "record")})
    return {"builders": audit["builders"]["raw"]["sha256"], **personal,
            "media": site.sha256(site.canonical(audit["media"]))}


def _media_review(item: dict, binding: dict, cached: dict | None, root: Path) -> list[Path]:
    review = site.obj(binding.get("review"), "产品取图 review")
    decision = review.get("decision")
    site.require(decision in ("selected", "no_candidates", "all_rejected", "download_failed"),
                 "产品取图 decision 必须明确分类")
    sources = site.array(review.get("sources"), "产品取图 sources")
    source_map = {}
    evidence_paths = []
    for source in sources:
        source = site.obj(source, "产品取图 source")
        url = site.source_url(source.get("url"), "产品取图 source.url")
        site.require(url not in source_map, "产品取图来源重复")
        site.require(source.get("status") in ("checked", "unavailable"), "产品取图来源状态无效")
        evidence_paths.append(_file(source.get("evidence"), root, "产品取图来源证据"))
        site.require(evidence_paths[-1].stat().st_size > 0, "产品取图来源证据不能为空文件")
        source_map[url] = source
    original = source_map.get(item["url"])
    site.require(original is not None, "产品取图必须逐条检查原文并保存证据")
    if original["status"] == "unavailable":
        site.require(any(row["status"] == "checked" for url, row in source_map.items() if url != item["url"]),
                     "原文不可访问时必须检查 newsletter 等替代来源")
    candidates = site.array(review.get("candidates"), "产品取图 candidates")
    selected = []
    candidate_urls = set()
    for candidate in candidates:
        candidate = site.obj(candidate, "产品取图 candidate")
        url = site.source_url(candidate.get("url"), "产品候选图.url")
        site.require(url not in candidate_urls, "产品候选图重复")
        candidate_urls.add(url)
        site.require(candidate.get("decision") in ("selected", "rejected", "download_failed"),
                     "产品候选图 decision 无效")
        site.string(candidate.get("reason"), "产品候选图判断原因")
        evidence_paths.append(_file(candidate.get("evidence"), root, "产品候选图证据"))
        site.require(evidence_paths[-1].stat().st_size > 0, "产品候选图证据不能为空文件")
        if candidate["decision"] == "selected":
            selected.append(url)
    if decision == "selected":
        site.require(item["image"] is not None and cached is not None and len(selected) == 1,
                     "已选图片必须绑定实际素材和唯一候选图")
        site.require(selected[0] in (cached.get("asset_url"), cached.get("resolved_url")),
                     "已选候选图 URL 与素材身份缓存不一致")
    else:
        site.require(item["image"] is None and not selected, "缺图分类不能含已选图片")
        missing = site.string(binding.get("missing"), "产品图缺失原因")
        # A generic blanket explanation is not an image search result.
        site.require(len(missing.strip()) >= 12 and missing.strip() not in
                     ("未获取到图片", "暂无图片", "没有合适图片", "测试无图"),
                     "缺图原因必须具体说明已检查来源及限制，不能使用统一占位说明")
        if decision == "no_candidates":
            site.require(not candidates, "no_candidates 不能含已发现候选图")
        elif decision == "all_rejected":
            site.require(bool(candidates) and all(row["decision"] == "rejected" for row in candidates),
                         "all_rejected 必须逐图保留拒绝原因与证据")
        else:
            site.require(bool(candidates) and any(row["decision"] == "download_failed" for row in candidates),
                         "download_failed 必须保留实际下载失败证据")
    return evidence_paths


def validate_media_checks(issue: dict, check: dict) -> None:
    rows = site.array(check.get("media_checks"), "Ego media_checks")
    expected = {item["url"]: item["image"] for category in ("featured", "personal")
                for item in issue["product"][category]}
    actual = {}
    for row in rows:
        row = site.obj(row, "Ego media_checks[]")
        url = site.source_url(row.get("url"), "Ego media_checks.url")
        site.require(url not in actual and url in expected, "Ego 图片覆盖含重复或多余条目")
        actual[url] = row
        image = expected[url]
        site.require("image_path" in row and row["image_path"] == (image["path"] if image else None),
                     "Ego 图片路径与本期数据不一致")
        site.require(type(row.get("rendered_count")) is int and row["rendered_count"] == (1 if image else 0),
                     "Ego 图片展示数量与本期数据不一致")
        site.require("loaded" in row and (row["loaded"] is True if image else row["loaded"] is None),
                     "Ego 图片未成功加载或无图状态错误")
    site.require(set(actual) == set(expected), "Ego 图片覆盖遗漏重点或关联条目")


def _media(issue: dict, audit: dict, assets_root: Path, root: Path) -> list[Path]:
    media = site.obj(audit.get("media"), "audit.media")
    products = site.array(media.get("products"), "media.products")
    product_map = {}
    for row in products:
        url = site.source_url(row.get("url"), "media.products.url")
        site.require(url not in product_map, "产品素材来源重复绑定")
        product_map[url] = row
    avatars = site.array(media.get("avatars"), "media.avatars")
    avatar_map = {}
    for row in avatars:
        author = site.string(row.get("author"), "media.avatars.author")
        site.require(author not in avatar_map, "缺失头像记录重复")
        avatar_map[author] = row
    index = site.load_json(assets_root / "asset-index.json")
    items = site.obj(index.get("items"), "asset-index.items")

    def bound(identity: str, path: str) -> None:
        record = site.obj(items.get(identity), f"asset-index[{identity}]")
        site.require(record.get("identity") == identity and record.get("path") == path,
                     f"素材身份或路径错绑：{identity}")
        site.require(record.get("visual_verified") is True, f"素材尚未视觉核对：{identity}")
        _, file = site.local_asset(path, assets_root, identity)
        site.require(record.get("sha256") == site.sha256(file.read_bytes()), f"素材缓存摘要不一致：{identity}")
        site.source_url(record.get("source_page"), identity + ".source_page")

    needed_products = []
    evidence_paths = []
    for category in ("featured", "personal"):
        for item in issue["product"][category]:
            url = item["url"]
            needed_products.append(url)
            site.require(url in product_map, "产品素材缺少绑定或缺失原因")
            record = product_map[url]
            if item["image"] is None:
                site.string(record.get("missing"), "产品图缺失原因")
                site.require("identity" not in record, "缺图记录不能同时声明已绑定素材")
            else:
                site.require("missing" not in record, "已配图不能声明缺失")
                bound(site.string(record.get("identity"), "产品图 identity"), item["image"]["path"])
            cached = items.get(record.get("identity")) if item["image"] is not None else None
            evidence_paths.extend(_media_review(item, record, cached, root))
    site.require(set(product_map) == set(needed_products) and len(needed_products) == len(set(needed_products)),
                 "产品素材绑定与本期重点/关联条目不一致")
    missing = set()
    for builder in issue["builders"]:
        author = builder["author"]
        if builder["avatar"] is None:
            missing.add(author)
            site.require(author in avatar_map, "头像缺失必须记录原因")
            binding = avatar_map[author]
            reason = site.string(binding.get("missing"), "头像缺失原因")
            site.require(len(reason.strip()) >= 12, "头像缺失原因必须具体，缓存未命中不能直接作为缺图结论")
            review = site.obj(binding.get("review"), "缺失头像 review")
            sources = site.array(review.get("sources"), "缺失头像 review.sources")
            site.require(bool(sources), "头像缺失必须实际检查作者或官方来源并保存证据")
            source_urls = set()
            for source in sources:
                source = site.obj(source, "缺失头像 source")
                url = site.source_url(source.get("url"), "缺失头像 source.url")
                site.require(url not in source_urls, "缺失头像来源重复")
                source_urls.add(url)
                site.require(source.get("status") in ("checked", "unavailable"), "缺失头像来源状态无效")
                path = _file(source.get("evidence"), root, "缺失头像来源证据")
                site.require(path.stat().st_size > 0, "缺失头像来源证据不能为空文件")
                evidence_paths.append(path)
        else:
            bound("avatar:" + author, builder["avatar"])
    site.require(set(avatar_map) == missing, "头像缺失记录与页面不一致")
    return evidence_paths


def preview_digest(path: Path) -> str:
    """Digest every regular candidate file, rejecting symbolic links."""
    site.require(path.is_dir(), "候选目录不存在")
    files = {}
    for file in sorted(path.rglob("*")):
        site.require(not file.is_symlink(), "候选目录不能含符号链接")
        if file.is_file():
            files[file.relative_to(path).as_posix()] = site.sha256(file.read_bytes())
    site.require(bool(files), "候选目录为空")
    return site.sha256(site.canonical(files))


def _qa(issue: dict, audit: dict, root: Path, assets_root: Path, source_paths: list[Path],
        started: datetime) -> dict:
    qa = site.obj(audit.get("qa"), "audit.qa")
    site.require(qa.get("passed") is True, "发布前缺少已通过的 Ego 验收签收")
    reviewed = timestamp(qa.get("reviewed_at"), "qa.reviewed_at")
    site.require(reviewed >= started, "浏览验收早于本次运行")
    read_at = (site.load_json(_file(audit["context"]["snapshot"], root, "context.snapshot"))["captured_at"]
               if audit.get("schema_version") == 2 else audit["todo"]["read_at"])
    site.require(reviewed >= timestamp(read_at, "personal.read_at"), "浏览验收早于本次个人参考读取")
    site.require(qa.get("source_sha256") == source_hashes(audit), "验收签收绑定的来源摘要与当前输入不一致")
    preview = Path(site.string(qa.get("preview_path"), "qa.preview_path")).resolve()
    manifest = site.load_json(preview / "manifest.json")
    generation = site.string(qa.get("generation"), "qa.generation")
    site.require(preview.name == generation == manifest.get("generation"), "验收候选版本不一致")
    site.require(preview_digest(preview) == _digest(qa.get("preview_sha256"), "qa.preview_sha256"),
                 "验收后候选文件已改变")
    renderer_hash = site.sha256(b"".join((site.PROJECT_ROOT / "scripts" / name).read_bytes()
                                      for name in ("render_issue.py", "personal_renderer.py")))
    site.require(manifest.get("renderer_sha256") == renderer_hash, "验收后页面模板已改变")
    site.require(site.sha256(site.canonical({"issues": manifest["issues"], "renderer": renderer_hash}))[:24] == generation,
                 "候选生成标识与清单不一致")
    day = issue["date"]
    record = site.obj(manifest["issues"].get(day), "候选本期记录")
    candidate_issue = site.load_json(preview / record["json"])
    site.require(site.canonical(candidate_issue) == site.canonical(issue), "验收后简报内容已改变")
    asset_paths = site.validate_issue(issue, assets_root)
    hashes = {name: site.sha256(file.read_bytes()) for name, file in sorted(asset_paths.items())}
    site.require(record.get("assets") == hashes, "验收后素材集合或内容已改变")
    site.require(record.get("sha256") == site.sha256(site.canonical({"issue": issue, "assets": hashes})),
                 "候选数据摘要与当前输入不一致")
    for name, digest in hashes.items():
        file = preview / "assets" / day / name[7:]
        site.require(file.is_file() and site.sha256(file.read_bytes()) == digest, "候选素材与本期输入不一致")
    for source in source_paths:
        site.require(source.stat().st_mtime <= reviewed.timestamp() + 1, "验收后来源文件被改写，请重新核对")
    evidence = site.array(qa.get("evidence"), "qa.evidence")
    kinds = set()
    for row in evidence:
        kind = row.get("kind")
        site.require(kind in ("ego-check", "screenshot"), "未知浏览验收证据类型")
        file = _file(row, root, "qa.evidence")
        if kind == "ego-check":
            check = site.load_json(file)
            site.require(check.get("tool") in ("ego-browser", "ego-lite") and check.get("passed") is True
                         and check.get("generation") == generation, "Ego 检查记录不匹配候选版本")
            validate_media_checks(issue, check)
        else:
            site.image_size(file)
        kinds.add(kind)
    site.require(kinds == {"ego-check", "screenshot"}, "验收必须保留 Ego 检查记录与实际截图")
    return {"generation": generation, "review": "recorded-ego-signoff"}


def validate_run_audit(issue: dict, audit_path: Path, assets_root: Path = site.DEFAULT_ASSETS_ROOT,
                       *, runs_root: Path = DEFAULT_RUNS_ROOT, require_qa: bool = False) -> dict:
    """Validate saved provenance; require candidate-bound Ego sign-off for publish."""
    root = runs_root.resolve()
    path = audit_path.resolve()
    site.require(path.is_relative_to(root) and path.is_file(), "审计文件必须保存在本项目 data/runs 内")
    audit = site.obj(site.load_json(path), "audit")
    site.require(type(audit.get("schema_version")) is int and audit["schema_version"] in (1, 2),
                 "审计 schema_version 必须为 1 或 2")
    run = site.obj(audit.get("run"), "audit.run")
    run_id = site.string(run.get("id"), "run.id")
    started = timestamp(run.get("started_at"), "run.started_at")
    site.require(audit.get("issue_sha256") == site.sha256(site.canonical(issue)), "本期内容不匹配审计输入")
    site.validate_issue(issue, assets_root)
    raw_path = _file(site.obj(audit.get("builders"), "audit.builders").get("raw"), root, "builders.raw")
    builders = validate_builders(issue, site.load_json(raw_path))
    if audit["schema_version"] == 2:
        personal, personal_paths = _context(issue, audit, root, started, run_id)
        personal_result = {"context": personal}
    else:
        personal_result = {"todo": _todo(issue, audit, root, started, run_id)}
        personal_paths = [_file(audit["todo"][key], root, "todo." + key) for key in ("page", "source", "record")]
    media_paths = _media(issue, audit, assets_root, root)
    result = {"status": "audited", "run_id": run_id, "builders": builders, **personal_result}
    if require_qa:
        sources = [raw_path] + media_paths + personal_paths
        result["qa"] = _qa(issue, audit, root, assets_root, sources, started)
    return result
