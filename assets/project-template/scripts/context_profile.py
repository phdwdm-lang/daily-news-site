#!/usr/bin/env python3
"""Project-local, opt-in context and explicit profile confirmation.

The host collects permitted conversation summaries or Page evidence and obtains
the user's actual choices. This command records those choices; a receipt is
traceability, not a technical proof of a conversation with the user. No network,
conversation search, JavaScript evaluation or inferred confirmation occurs here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import daily_site as site

FACT_TYPES = ("role", "interest", "goal", "project", "experience", "task", "document")
MODES = ("none", "profile", "context")


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value, label):
    site.string(value, label)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise site.ValidationError(label + " 不是有效时间") from exc
    site.require(result.tzinfo is not None and result.utcoffset() is not None, label + " 必须带时区")
    return result


def default_config():
    return {"schema_version": 1, "timezone": "Asia/Shanghai", "theme": "light",
            "context": {"mode": "none", "profile_path": ".daily-news/profile.json",
                        "sources": [], "fallback": "error"}}


def validate_config(config):
    config = site.obj(config, "config")
    site.require(config.get("schema_version") == 1, "config.schema_version 必须为 1")
    context = site.obj(config.get("context"), "config.context")
    site.require(context.get("mode") in MODES, "context.mode 必须为 none/profile/context")
    site.require(context.get("fallback", "error") in ("error", "none", "profile"), "context.fallback 无效")
    if "profile_path" in context:
        site.string(context["profile_path"], "context.profile_path")
    ids = []
    for source in site.array(context.get("sources", []), "context.sources"):
        source = site.obj(source, "context.sources[]")
        source_id = site.string(source.get("id"), "context.source.id")
        site.require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", source_id) is not None,
                     "context.source.id 只接受字母、数字、点、横线和下划线")
        ids.append(source_id)
        site.require(source.get("kind") in ("local", "page"), "context.source.kind 必须为 local/page")
        site.string(source.get("path"), "context.source.path")
        if source["kind"] == "page":
            site.string(source.get("page_id"), "context.source.page_id")
            timestamp(source.get("read_at"), "context.source.read_at")
        if source.get("reference") is not None:
            site.string(source["reference"], "context.source.reference")
    site.require(len(ids) == len(set(ids)), "context.sources ID 重复")
    return config


def load_config(project):
    path = Path(project).resolve() / ".daily-news/config.json"
    # Absence is an intentional generic default. An unreadable/malformed existing
    # configuration is an error; it is never silently treated as absent.
    return validate_config(site.load_json(path) if path.exists() or path.is_symlink() else default_config())


def _project_file(project, path):
    path = Path(path)
    return (path if path.is_absolute() else Path(project) / path).resolve()


def _profile_path(project, config):
    path = _project_file(project, config["context"].get("profile_path", ".daily-news/profile.json"))
    site.require(path.is_relative_to((Path(project).resolve() / ".daily-news").resolve()),
                 "profile_path 必须位于目标项目 .daily-news 内")
    return path


def _sources(value, label):
    sources = site.array(value, label)
    site.require(bool(sources), label + " 不能为空")
    for source in sources:
        source = site.obj(source, label + "[]")
        site.string(source.get("kind"), label + ".kind")
        site.string(source.get("reference"), label + ".reference")
        timestamp(source.get("read_at"), label + ".read_at")
        if source.get("activity_at") is not None:
            timestamp(source["activity_at"], label + ".activity_at")
    return [{key: source[key] for key in ("kind", "reference", "read_at", "activity_at") if key in source}
            for source in sources]


def _base_fact(fact, label):
    fact = site.obj(fact, label)
    site.string(fact.get("id"), label + ".id")
    site.require(fact.get("type") in FACT_TYPES, label + ".type 无效")
    site.string(fact.get("text"), label + ".text")
    _sources(fact.get("sources"), label + ".sources")
    return fact


def validate_profile(profile):
    profile = site.obj(profile, "profile")
    site.require(profile.get("schema_version") == 1, "profile.schema_version 必须为 1")
    facts = site.array(profile.get("facts"), "profile.facts")
    ids = []
    for fact in facts:
        fact = _base_fact(fact, "profile.fact")
        ids.append(fact["id"])
        site.require(fact.get("status") == "confirmed", "profile 只能含用户已明确确认的事实，candidate 不能使用")
        confirmed = timestamp(fact.get("confirmed_at"), "profile.fact.confirmed_at")
        receipt = site.obj(fact.get("confirmation_receipt"), "profile.fact.confirmation_receipt")
        site.require(receipt.get("method") == "host-interaction", "确认必须来自宿主实际用户交互")
        site.string(receipt.get("reference"), "confirmation_receipt.reference")
        site.require(receipt.get("confirmed_at") == fact["confirmed_at"], "事实确认时间与交互回执不一致")
        site.require(all(confirmed >= timestamp(source["read_at"], "source.read_at") for source in fact["sources"]),
                     "确认不能早于候选来源读取")
    site.require(len(ids) == len(set(ids)), "profile 事实 ID 重复")
    return profile


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    site.write_file(temporary, site.canonical(value))
    temporary.replace(path)


def save_candidates(project, input_path):
    value = site.load_json(Path(input_path))
    rows = value if isinstance(value, list) else site.array(value.get("candidates"), "candidates")
    path = Path(project).resolve() / ".daily-news/context-candidates.json"
    existing = site.load_json(path) if path.exists() else {"schema_version": 1, "candidates": []}
    merged = {row["id"]: row for row in site.array(existing.get("candidates"), "candidates")}
    reviews = site.array(existing.get("reviews", []), "candidate.reviews")
    processed = {row["id"] for row in reviews}
    for row in rows:
        row = site.obj(row, "candidate")
        site.require(row.get("status", "candidate") == "candidate", "候选导入不能声明已获用户确认")
        kind = row.get("type")
        site.require(kind in FACT_TYPES, "candidate.type 无效")
        text = site.string(row.get("text"), "candidate.text")
        sources = _sources(row.get("sources"), "candidate.sources")
        # Read times and retrieval order do not change an existing candidate ID.
        identity = {"type": kind, "text": text, "sources": sorted({source["reference"] for source in sources})}
        fact_id = "ctx-" + site.sha256(site.canonical(identity))[:20]
        if fact_id not in merged and fact_id not in processed:
            merged[fact_id] = {"id": fact_id, "type": kind, "text": text,
                               "sources": sources, "status": "candidate"}
    result = {"schema_version": 1, "candidates": list(merged.values()), "reviews": reviews}
    _write(path, result)
    return {"status": "candidates-saved", "path": str(path), "candidates": result["candidates"]}


def review_candidates(project, decisions_path):
    project = Path(project).resolve()
    path = project / ".daily-news/context-candidates.json"
    candidates = site.load_json(path)
    by_id = {row["id"]: row for row in site.array(candidates.get("candidates"), "candidates")}
    decisions = site.obj(site.load_json(Path(decisions_path)), "decisions")
    receipt = site.obj(decisions.get("receipt"), "receipt")
    site.require(receipt.get("method") == "host-interaction", "receipt 必须记录宿主实际用户交互")
    site.string(receipt.get("reference"), "receipt.reference")
    confirmed_at = site.string(receipt.get("confirmed_at"), "receipt.confirmed_at")
    timestamp(confirmed_at, "receipt.confirmed_at")
    config = load_config(project)
    profile_path = _profile_path(project, config)
    profile = validate_profile(site.load_json(profile_path) if profile_path.exists() else {"schema_version": 1, "facts": []})
    facts = {fact["id"]: fact for fact in profile["facts"]}
    reviews = site.array(candidates.get("reviews", []), "candidate.reviews")
    seen = set()
    for decision in site.array(decisions.get("decisions"), "decisions.decisions"):
        decision = site.obj(decision, "decision")
        fact_id = site.string(decision.get("id"), "decision.id")
        site.require(fact_id in by_id and fact_id not in seen, "选择含不存在或重复的候选 ID")
        seen.add(fact_id)
        action = decision.get("action")
        site.require(action in ("confirm", "edit", "ignore"), "action 必须为 confirm/edit/ignore")
        row = by_id[fact_id]
        if action == "ignore":
            facts.pop(fact_id, None)
            reviews.append({"id": fact_id, "action": action, "receipt": receipt})
            continue
        fact = {key: row[key] for key in ("id", "type", "text", "sources")}
        if action == "edit":
            fact["text"] = site.string(decision.get("text"), "decision.text")
            if "type" in decision:
                site.require(decision["type"] in FACT_TYPES, "decision.type 无效")
                fact["type"] = decision["type"]
        fact.update(status="confirmed", confirmed_at=confirmed_at, confirmation_receipt=receipt)
        facts[fact_id] = fact
        reviews.append({"id": fact_id, "action": action, "receipt": receipt})
    result = validate_profile({"schema_version": 1, "facts": list(facts.values())})
    candidates["candidates"] = [row for row in candidates["candidates"] if row["id"] not in seen]
    candidates["reviews"] = reviews
    # All validation precedes any mutation; invalid selections cannot partly save.
    _write(profile_path, result)
    _write(path, candidates)
    return {"status": "review-recorded", "profile": str(profile_path), "facts": result["facts"]}


def source_facts(data, suffix, source_id, provenance):
    """Extract selected evidence without pretending it was a confirmed profile."""
    text = data.decode("utf-8")
    if suffix.lower() in (".md", ".markdown", ".txt"):
        rows = [{"type": "document", "text": text}] if text.strip() else []
    else:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise site.ValidationError("个人参考源必须为 JSON 或 Markdown；不会执行 HTML/脚本") from exc
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict) and "candidates" in value:
            raise site.ValidationError("未确认候选不能作为个人参考来源；先取得用户选择并review")
        elif isinstance(value, dict) and ("facts" in value or "tasks" in value):
            rows = site.array(value.get("facts", value.get("tasks")), "source.facts/tasks")
        else:
            # Page tool envelopes are preserved whole as document evidence.
            rows = [{"type": "document", "text": text}]
    result = []
    ids = set()
    for row in rows:
        row = site.obj(row, "source.fact")
        site.require(row.get("status") not in ("candidate", "ignored"), "未确认或忽略的候选不能作为个人依据")
        fact_type = row.get("type", "task" if "title" in row else "document")
        site.require(fact_type in FACT_TYPES, "source.fact.type 无效")
        content = site.string(row.get("text", row.get("title")), "source.fact.text/title")
        local_id = row.get("id") or site.sha256(site.canonical(row))[:20]
        site.require(isinstance(local_id, (str, int)), "source.fact.id 必须是字符串或整数")
        fact_id = source_id + ":" + str(local_id)
        site.require(fact_id not in ids, "source.fact.id 重复")
        ids.add(fact_id)
        result.append({"id": fact_id, "type": fact_type, "text": content, "status": "source",
                       "sources": [provenance], "source_fields": row})
    return result


def snapshot(project, run_dir, *, refresh=False):
    project, run_dir = Path(project).resolve(), Path(run_dir).resolve()
    site.require(run_dir.is_relative_to(project / "data/runs"), "run-dir 必须位于目标项目 data/runs 内")
    run = site.obj(site.load_json(run_dir / "run.json"), "run.json")
    started = timestamp(run.get("started_at"), "run.started_at")
    target = run_dir / "context"
    site.require(refresh or not target.exists(), "个人参考快照已存在；明确 --refresh 后使后续审计重新验收")
    config = load_config(project)
    captured_at = now()
    site.require(timestamp(captured_at, "captured_at") >= started, "运行开始时间晚于实际读取")
    temporary = run_dir / (".context-" + uuid.uuid4().hex)
    temporary.mkdir()
    records, facts, errors = [], [], []
    context = config["context"]
    mode, effective = context["mode"], context["mode"]

    def record(name, data):
        site.write_file(temporary / name, data)
        # Relative records remain verifiable when an explicit refresh archives
        # the entire previous snapshot directory unchanged.
        return {"path": name, "sha256": site.sha256(data)}

    config_record = record("config.json", site.canonical(config))
    profile_record = None
    try:
        if mode in ("profile", "context"):
            profile_path = _profile_path(project, config)
            if profile_path.exists():
                profile = validate_profile(site.load_json(profile_path))
                profile_record = record("profile.json", site.canonical(profile))
                facts.extend(profile["facts"])
            elif mode == "profile":
                # No confirmed facts yet is a valid, empty personal profile.
                profile_record = record("profile.json", site.canonical({"schema_version": 1, "facts": []}))
        if mode == "context":
            site.require(bool(context.get("sources")), "context 模式没有明确选择的参考源")
            for source in context["sources"]:
                try:
                    original = _project_file(project, source["path"])
                    data = original.read_bytes()
                    if source["kind"] == "page":
                        read_at = source["read_at"]
                        site.require(started <= timestamp(read_at, "page.read_at") <= timestamp(captured_at, "captured_at"),
                                     "Page 证据早于本次运行；须由宿主重新读取")
                        site.require(source["page_id"] in data.decode("utf-8"), "Page 证据不含所选 page_id")
                        if source.get("reference"):
                            site.require(source["reference"] in data.decode("utf-8"), "Page 证据不含所选 reference")
                    else:
                        read_at = captured_at
                    provenance = {"kind": source["kind"], "reference": source.get("reference", str(original)), "read_at": read_at}
                    if source.get("activity_at") is not None:
                        timestamp(source["activity_at"], "source.activity_at")
                        provenance["activity_at"] = source["activity_at"]
                    suffix = original.suffix.lower() or ".json"
                    derived = source_facts(data, suffix, source["id"], provenance)
                    records.append({"id": source["id"], "kind": source["kind"], "original_path": str(original),
                                    "suffix": suffix, "read_at": read_at, "provenance": provenance,
                                    "file": record("sources/" + source["id"] + suffix, data)})
                    facts.extend(derived)
                except (OSError, UnicodeError, site.ValidationError) as exc:
                    errors.append({"id": source["id"], "kind": source["kind"], "status": "unavailable", "error": str(exc)})
            if errors:
                fallback = context.get("fallback", "error")
                site.require(fallback != "error", "个人参考源不可读；按配置停止：" + "; ".join(row["error"] for row in errors))
                effective = fallback
                facts = [fact for fact in facts if fact["status"] == "confirmed"] if fallback == "profile" else []
        value = {"schema_version": 1, "run_id": run["id"], "captured_at": captured_at,
                 "mode": mode, "effective_mode": effective, "config": config_record,
                 "profile": profile_record, "sources": records, "source_errors": errors, "facts": facts}
        site.require(len({fact["id"] for fact in facts}) == len(facts), "个人参考事实 ID 冲突")
        site.write_file(temporary / "snapshot.json", site.canonical(value))
        # Explicit refresh is retained for audit/history, never silently replaced.
        if target.exists():
            history = run_dir / "context-history"
            history.mkdir(exist_ok=True)
            target.rename(history / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]))
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"status": "context-snapshotted", "snapshot": str(target / "snapshot.json"),
            "mode": mode, "effective_mode": effective, "facts": len(facts), "source_errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=site.PROJECT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("candidates", "review"):
        child = sub.add_parser(command)
        child.add_argument("--input" if command == "candidates" else "--decisions", type=Path, required=True)
    child = sub.add_parser("snapshot")
    child.add_argument("--run-dir", type=Path, required=True)
    child.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "candidates":
            result = save_candidates(args.project_root, args.input)
        elif args.command == "review":
            result = review_candidates(args.project_root, args.decisions)
        else:
            result = snapshot(args.project_root, args.run_dir, refresh=args.refresh)
    except (site.ValidationError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
