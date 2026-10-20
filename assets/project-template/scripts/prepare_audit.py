#!/usr/bin/env python3
"""Prepare source-bound daily audit records, then bind an existing Ego review.

This tool computes file hashes and extracts saved task JSON. It does not fetch
sources, decide relevance, invent review times, or perform a browser review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

import daily_site as site
import run_audit as gate


def _inside(path: Path, root: Path, label: str, *, exists: bool = True) -> Path:
    path = path.resolve()
    site.require(path.is_relative_to(root.resolve()), label + " 必须保存在本项目 data/runs 内")
    if exists:
        site.require(path.is_file(), label + " 文件不存在")
    return path


def file_record(path: Path, root: Path) -> dict:
    path = _inside(path, root, "来源/证据")
    return {"path": str(path), "sha256": site.sha256(path.read_bytes())}


def visualize_reference(page: Any) -> str:
    references: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            references.update(re.findall(r"visualize:[A-Za-z0-9_][A-Za-z0-9_./:%?=&~+\-]*", value))
        elif isinstance(value, dict):
            for part in value.values():
                walk(part)
        elif isinstance(value, list):
            for part in value:
                walk(part)

    walk(page)
    site.require(len(references) == 1, "待办页面必须含唯一的 visualize 引用；零个或多个均需明确来源")
    return next(iter(references))


def selected_page_id(page: Any) -> str:
    """A legacy Page identifies itself; the distributable has no author's ID."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, part in value.items():
                if key in ("id", "page_id", "pageId") and isinstance(part, str) and part.startswith("page_"):
                    found.add(part)
                walk(part)
        elif isinstance(value, list):
            for part in value:
                walk(part)

    walk(page)
    site.require(len(found) == 1, "旧版待办Page必须明确返回唯一的页面ID")
    return next(iter(found))


def create_audit(*, issue_path: Path, run_dir: Path, builders_raw: Path,
                 todo_page: Path | None = None, todo_source: Path | None = None,
                 context_snapshot: Path | None = None, bindings_path: Path,
                 output: Path, assets_root: Path = site.DEFAULT_ASSETS_ROOT,
                 runs_root: Path = gate.DEFAULT_RUNS_ROOT) -> dict:
    root = runs_root.resolve()
    run_dir = run_dir.resolve()
    site.require(run_dir.is_relative_to(root) and run_dir.is_dir(), "run-dir 必须是 data/runs 内的运行目录")
    run = site.obj(site.load_json(run_dir / "run.json"), "run.json")
    run_id = site.string(run.get("id", run_dir.name), "run.id")
    started = gate.timestamp(run.get("started_at"), "run.started_at")
    issue = site.obj(site.load_json(issue_path), "issue")
    site.require(run.get("date") == issue.get("date"), "run.json 日期与简报日期不一致")
    read_at = datetime.now(timezone.utc)
    site.require(read_at >= started, "run.started_at 晚于实际读取时间")
    legacy = todo_page is not None or todo_source is not None
    site.require(not legacy or (todo_page is not None and todo_source is not None), "旧版审计必须同时提供todo-page和todo-source")
    site.require(not (legacy and context_snapshot is not None), "不能混用旧版待办与v2个人参考快照")
    if legacy:
        page = site.load_json(_inside(todo_page, root, "待办页面"))
        page_id = selected_page_id(page)
        reference = visualize_reference(page)
        source_record = file_record(todo_source, root)
        tasks = gate.parse_tasks(Path(source_record["path"]).read_text(encoding="utf-8"))
    else:
        context_snapshot = context_snapshot or run_dir / "context/snapshot.json"
        gate.context_snapshot(file_record(context_snapshot, root), root, started, run_id)
    bindings = site.obj(site.load_json(bindings_path), "bindings")
    record_path = run_dir / "todo-record.json"
    output = _inside(output, root, "审计输出", exists=False)
    inputs = {path.resolve() for path in (issue_path, builders_raw, todo_page, todo_source, context_snapshot,
                                         bindings_path, run_dir / "run.json") if path is not None}
    site.require(record_path not in inputs and output not in inputs and output != record_path,
                 "审计/提取输出不能覆盖原始输入")
    products = site.array(bindings.get("products"), "bindings.products")
    for product in products:
        review = site.obj(product.get("review"), "bindings.products.review")
        for category in ("sources", "candidates"):
            for row in site.array(review.get(category), "review." + category):
                # The helper owns every hash. Caller-provided evidence objects
                # cannot bypass reading the exact saved file bytes.
                evidence = Path(site.string(row.pop("evidence_path", None), "review.evidence_path"))
                site.require(evidence.is_absolute(), "review.evidence_path 必须是绝对路径")
                row["evidence"] = file_record(evidence, root)
    missing_avatars = site.array(bindings.get("missing_avatars"), "bindings.missing_avatars")
    for avatar in missing_avatars:
        review = site.obj(avatar.get("review"), "bindings.missing_avatars.review")
        for row in site.array(review.get("sources"), "missing_avatars.review.sources"):
            evidence = Path(site.string(row.pop("evidence_path", None), "review.evidence_path"))
            site.require(evidence.is_absolute(), "review.evidence_path 必须是绝对路径")
            row["evidence"] = file_record(evidence, root)
    if legacy:
        record = {"run_id": run_id, "page_id": page_id, "reference": reference,
                  "read_at": read_at.isoformat(), "source_sha256": source_record["sha256"], "tasks": tasks}
        site.write_file(record_path, site.canonical(record))
        personal = {"todo": {"page_id": page_id, "reference": reference,
                            "read_at": record["read_at"], "page": file_record(todo_page, root),
                            "source": source_record, "record": file_record(record_path, root)}}
    else:
        personal = {"context": {"snapshot": file_record(context_snapshot, root)}}
    audit = {"schema_version": 1 if legacy else 2, "run": {"id": run_id, "started_at": run["started_at"]},
             "issue_sha256": site.sha256(site.canonical(issue)),
             "builders": {"raw": file_record(builders_raw, root)},
             **personal,
             "personal_bindings": site.array(bindings.get("personal_bindings"), "bindings.personal_bindings"),
             "media": {"products": products,
                       "avatars": missing_avatars}}
    site.write_file(output, site.canonical(audit))
    # Validation is authoritative. A failed preparation remains an input draft,
    # never a publication or successful sign-off.
    result = gate.validate_run_audit(issue, output, assets_root, runs_root=root)
    return {**result, "status": "prepared", "audit": str(output),
            "record": str(record_path if legacy else context_snapshot)}


def signoff(*, issue_path: Path, audit_path: Path, preview_dir: Path,
            ego_check: Path, screenshot: Path, assets_root: Path = site.DEFAULT_ASSETS_ROOT,
            runs_root: Path = gate.DEFAULT_RUNS_ROOT) -> dict:
    root = runs_root.resolve()
    audit_path = _inside(audit_path, root, "审计")
    issue = site.obj(site.load_json(issue_path), "issue")
    gate.validate_run_audit(issue, audit_path, assets_root, runs_root=root)
    audit = site.obj(site.load_json(audit_path), "audit")
    check = site.obj(site.load_json(_inside(ego_check, root, "Ego 检查")), "Ego 检查")
    site.require(check.get("tool") in ("ego-browser", "ego-lite") and check.get("passed") is True,
                 "Ego 检查必须已有真实 tool 与 passed:true")
    reviewed_at = site.string(check.get("reviewed_at"), "Ego reviewed_at")
    gate.timestamp(reviewed_at, "Ego reviewed_at")
    preview_dir = preview_dir.resolve()
    manifest = site.obj(site.load_json(preview_dir / "manifest.json"), "候选 manifest")
    generation = site.string(check.get("generation"), "Ego generation")
    site.require(generation == manifest.get("generation"), "Ego 检查与候选版本不同")
    audit["qa"] = {"passed": True, "reviewed_at": reviewed_at,
                   "preview_path": str(preview_dir), "generation": generation,
                   "preview_sha256": gate.preview_digest(preview_dir),
                   "source_sha256": gate.source_hashes(audit),
                   "evidence": [{"kind": "ego-check", **file_record(ego_check, root)},
                                {"kind": "screenshot", **file_record(screenshot, root)}]}
    # Check the proposed signed record before replacing the prepared input.
    pending = audit_path.with_name(audit_path.name + ".pending")
    site.write_file(pending, site.canonical(audit))
    try:
        result = gate.validate_run_audit(issue, pending, assets_root, runs_root=root, require_qa=True)
        pending.replace(audit_path)
    finally:
        pending.unlink(missing_ok=True)
    return {**result, "status": "signed", "audit": str(audit_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="从本次保存的输入提取待办并计算审计摘要，不生成 QA")
    create.add_argument("--issue", type=Path, required=True)
    create.add_argument("--run-dir", type=Path, required=True)
    create.add_argument("--builders-raw", type=Path, required=True)
    create.add_argument("--todo-page", type=Path, help="仅兼容旧版Page任务来源")
    create.add_argument("--todo-source", type=Path, help="仅兼容旧版const tasks文件")
    create.add_argument("--context-snapshot", type=Path, help="默认RUN/context/snapshot.json，支持none/profile/context")
    create.add_argument("--bindings", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--assets-root", type=Path, default=site.DEFAULT_ASSETS_ROOT)
    review = sub.add_parser("signoff", help="绑定已完成的 Ego 检查及截图；不自动生成验收结论或时间")
    review.add_argument("--issue", type=Path, required=True)
    review.add_argument("--audit", type=Path, required=True)
    review.add_argument("--preview-dir", type=Path, required=True)
    review.add_argument("--ego-check", type=Path, required=True)
    review.add_argument("--screenshot", type=Path, required=True)
    review.add_argument("--assets-root", type=Path, default=site.DEFAULT_ASSETS_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_audit(issue_path=args.issue, run_dir=args.run_dir, builders_raw=args.builders_raw,
                                  todo_page=args.todo_page, todo_source=args.todo_source,
                                  context_snapshot=args.context_snapshot,
                                  bindings_path=args.bindings, output=args.output, assets_root=args.assets_root)
        else:
            result = signoff(issue_path=args.issue, audit_path=args.audit, preview_dir=args.preview_dir,
                             ego_check=args.ego_check, screenshot=args.screenshot, assets_root=args.assets_root)
    except (site.ValidationError, OSError, ImportError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
