#!/usr/bin/env python3
"""Durable daily-run checkpoints; never substitutes for editing or real Ego review.

Source responses stay in immutable numbered attempts. workflow.json is a compact
resume index, and workflow-events retain every completed/invalidated checkpoint.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

import daily_site as site
import run_audit as gate
import context_profile as context

PHASES = ("inputs", "editorial", "media", "audit", "preview", "review", "published")
NEXT = {
    "inputs": "采集未完成分支；重新读取待办 Page 及实际引用文件，保存 todo/page.json 和 todo/source.html。",
    "editorial": "完整读全部来源与待办；保存统一工作稿及当期 JSON，不能只读本摘要。",
    "media": "逐条取图/查缺图，实际看图；保存 bindings 和证据，执行 prepare_audit.py create。",
    "audit": "核验来源与素材审计。",
    "preview": "执行 daily_site.py validate --audit ... --preview-root ... 生成候选。",
    "review": "用 Ego 实际验收候选、逐图检查及截图，再执行 prepare_audit.py signoff。",
    "published": "执行 daily_site.py publish --audit ...，并复查当前入口。",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    site.write_file(temporary, site.canonical(value))
    os.replace(temporary, path)


@contextmanager
def lock(run):
    with (run / ".workflow.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise site.ValidationError("本运行已有操作进行中；不重复采集或抢占锁。") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def event(run, state, kind, **values):
    sequence = state.get("sequence", 0) + 1
    record = {"sequence": sequence, "at": now(), "kind": kind, **values}
    path = run / "workflow-events" / f"{sequence:06d}.json"
    site.require(not path.exists(), "工作流事件冲突；保留旧记录，不覆盖。")
    site.write_file(path, site.canonical(record))
    state["sequence"] = sequence


def save(run, state):
    state["updated_at"] = now()
    atomic_json(run / "workflow.json", state)


def init_run(*, runs_root=gate.DEFAULT_RUNS_ROOT, date=None, run_id=None, timezone_name="Asia/Shanghai"):
    day = date or datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    site.issue_date(day)
    run_id = run_id or "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    site.require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", run_id)), "run-id 只接受字母、数字、点、横线及下划线")
    run = runs_root.resolve() / day / run_id
    site.require(not run.exists(), "运行目录已存在；用 status/collect 续跑，不覆盖旧运行。")
    run.mkdir(parents=True)
    project = runs_root.resolve().parent.parent
    config_path = project / ".daily-news/config.json"
    configured = config_path.exists() or config_path.is_symlink()
    metadata = {"schema_version": 2 if configured else 1, "id": run_id, "date": day, "timezone": timezone_name,
                "started_at": now(), "selection": {"mode": "as-of" if date else "latest", "date": date}}
    site.write_file(run / "run.json", site.canonical(metadata))
    state = {"schema_version": 1, "run": metadata, "branches": {}, "phases": {}, "sequence": 0}
    event(run, state, "initialized", selection=metadata["selection"])
    save(run, state)
    personal = None
    if configured:
        try:
            personal = context.snapshot(project, run)
            event(run, state, "context-snapshotted", **personal)
        except (site.ValidationError, OSError, ValueError) as exc:
            # A Page must be read after this run starts. Keep the new identity
            # recoverable while the host fetches the selected Page evidence.
            personal = {"status": "needs-input", "error": str(exc), "run_dir": str(run),
                        "next_action": "保留此运行；宿主补齐本轮真实读取证据，再执行context_profile.py snapshot --run-dir RUN。"}
            event(run, state, "context-pending", **personal)
        save(run, state)
    return {"status": "initialized", "run_dir": str(run), "selection": metadata["selection"],
            "personalization": personal or {"mode": "legacy", "message": "既有工程未配置，保留v1待办流程；新工程先setup。"}}


def load(run):
    state = site.load_json(run / "workflow.json")
    site.require(state.get("schema_version") == 1, "不支持的 workflow schema")
    site.require(state["run"] == site.load_json(run / "run.json"), "run.json 在初始化后改变；请创建新运行。")
    # A process may stop after fsyncing an event but before replacing the index.
    # Keep its record, advance the sequence, and resume from verified checkpoints.
    journal = run / "workflow-events"
    state["sequence"] = max([state.get("sequence", 0)] +
                            [int(path.stem) for path in journal.glob("*.json") if path.stem.isdigit()])
    return state


def fingerprint(path, mode="file"):
    path = Path(path)
    if mode == "tree":
        site.require(path.is_dir(), "目录缺失：" + str(path))
        # A branch pointer is allowed, but no nested symlinks to arbitrary files.
        root = path.resolve()
        files = {}
        for child in sorted(root.rglob("*")):
            site.require(not child.is_symlink(), "来源/候选目录内部不能含符号链接")
            if child.is_file():
                files[child.relative_to(root).as_posix()] = site.sha256(child.read_bytes())
        site.require(bool(files), "目录为空：" + str(path))
        digest = site.sha256(site.canonical(files))
    elif mode == "audit-input":
        value = site.load_json(path)
        value.pop("qa", None)  # Signing does not invalidate input-only audit checkpoints.
        digest = site.sha256(site.canonical(value))
    else:
        digest = site.sha256(path.read_bytes())
    return {"path": str(path.absolute()), "mode": mode, "sha256": digest}


def reconcile(run, state):
    invalid = None
    for phase in PHASES:
        record = state["phases"].get(phase)
        if not record or record.get("status") != "complete":
            continue
        if invalid is None:
            try:
                changed = any(fingerprint(row["path"], row["mode"])["sha256"] != row["sha256"]
                              for row in record["artifacts"])
            except (OSError, site.ValidationError):
                changed = True
            if changed:
                invalid = phase
        if invalid is not None:
            record.update(status="stale", reason="输入或证据变化：" + invalid, invalidated_at=now())
            event(run, state, "invalidated", phase=phase, changed_phase=invalid)
    return invalid


def report(run, state):
    next_phase = next((phase for phase in PHASES if state["phases"].get(phase, {}).get("status") != "complete"), None)
    action = NEXT.get(next_phase, "本地提交已核验；线上部署另行执行。")
    if state["run"].get("schema_version") == 2 and next_phase in ("inputs", "editorial"):
        action = ("采集未完成分支；核验本运行context/snapshot.json及所选个人参考源，none模式无需个人资料。"
                  if next_phase == "inputs" else "完整读全部来源与已选择的个人参考；保存统一工作稿及当期JSON。")
        if not (run / "context/snapshot.json").is_file():
            action = "个人参考快照待补齐；宿主读取所选来源后执行context_profile.py snapshot --run-dir RUN。采集可继续。"
    return {"status": "complete" if next_phase is None else "pending", "run_dir": str(run),
            "date": state["run"]["date"], "selection": state["run"]["selection"],
            "branches": {key: {k: value[k] for k in ("status", "attempt", "output_dir") if k in value}
                         for key, value in state["branches"].items()},
            "phases": {phase: state["phases"].get(phase, {}).get("status", "pending") for phase in PHASES},
            "next_phase": next_phase, "next_action": action}


def source_state(branch, output):
    filename = "raw.json" if branch == "builders" else "products-manifest.json"
    value = site.load_json(output / filename)
    status = value.get("status") if branch == "builders" else value.get("state")
    if status in ("ok", "fetched_all_sources"):
        return "returned"
    if status in ("partial", "partial_sources"):
        return "partial"
    return "failed"


def collect(run, state, *, package=None, runner=subprocess.run):
    package = (package or site.PROJECT_ROOT / "skills/daily-news-site").resolve()
    selected = []
    for branch in ("builders", "products"):
        previous = state["branches"].get(branch, {})
        try:
            unchanged = (previous.get("status") == "returned" and
                         fingerprint(Path(previous["output_dir"]), "tree")["sha256"] == previous.get("sha256"))
        except (OSError, KeyError, site.ValidationError):
            unchanged = False
        if not unchanged:
            selected.append(branch)
    if not selected:
        return {**report(run, state), "collection": "reused",
                "message": "沿用本运行已成功的采集及真实获取时间；未重复下载。"}
    attempt_root = run / "attempts"
    attempt_root.mkdir(exist_ok=True)
    number = max([int(p.name) for p in attempt_root.iterdir() if p.name.isdigit()] or [0]) + 1
    attempt = attempt_root / f"{number:04d}"
    attempt.mkdir()
    event(run, state, "collection-started", attempt=number, branches=selected)
    save(run, state)  # Interrupted attempts remain visible and never get overwritten.

    def execute(branch):
        output = attempt / branch
        output.mkdir()
        command = ["node", str(package / "scripts" / (branch + "-source.mjs")), "--output-dir", str(output),
                   "--mode", state["run"]["selection"]["mode"], "--timezone", state["run"]["timezone"]]
        if state["run"]["selection"]["date"]:
            command += ["--date", state["run"]["selection"]["date"]]
        try:
            completed = runner(command, capture_output=True, text=True, timeout=300)
            (output / "collector.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (output / "collector.stderr.log").write_text(completed.stderr, encoding="utf-8")
            status = source_state(branch, output)
            return branch, {"status": status, "exit_code": completed.returncode}
        except (OSError, subprocess.SubprocessError, site.ValidationError) as exc:
            (output / "collector-error.txt").write_text(str(exc), encoding="utf-8")
            return branch, {"status": "failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, selected))
    for branch, result in results:
        output = attempt / branch
        result.update(attempt=number, output_dir=str(output), finished_at=now(),
                      sha256=fingerprint(output, "tree")["sha256"])
        # Stable aliases never overwrite actual files, only our own previous pointer.
        pointer = run / branch
        site.require(not pointer.exists() or pointer.is_symlink(), "拒绝覆盖旧原始目录：" + str(pointer))
        temporary = run / ("." + branch + "-" + uuid.uuid4().hex)
        temporary.symlink_to(output.relative_to(run), target_is_directory=True)
        os.replace(temporary, pointer)
        state["branches"][branch] = result
        event(run, state, "collection-result", branch=branch, **result)
    reconcile(run, state)
    save(run, state)
    return report(run, state)


def _checkpoint(run, state, phase, *, issue_path=None, editorial=None, audit_path=None,
               preview_dir=None, assets_root=site.DEFAULT_ASSETS_ROOT, site_root=site.DEFAULT_SITE_ROOT,
               runs_root=gate.DEFAULT_RUNS_ROOT):
    reconcile(run, state)
    index = PHASES.index(phase)
    site.require(all(state["phases"].get(p, {}).get("status") == "complete" for p in PHASES[:index]),
                 "前置步骤未完成或已失效；先执行 status 查看断点。")
    artifacts = []
    evidence = {"scope": "artifact-validation-only; semantic and visual decisions remain agent work"}
    if phase == "inputs":
        for branch in ("builders", "products"):
            source = run / branch
            site.require(source_state(branch, source) in ("returned", "partial"), "分支无有效输入：" + branch)
            artifacts.append(fingerprint(source, "tree"))
        raw = site.load_json(run / "builders/raw.json")
        products = site.load_json(run / "products/products-manifest.json")
        has_builders = (any(person.get("tweets") for person in raw.get("x", []))
                        or bool(raw.get("podcasts")) or bool(raw.get("blogs")))
        has_products = any(source.get("state") == "fetched" and source.get("body_characters", 0) > 0
                           for source in products.get("sources", []))
        site.require(has_builders or has_products, "所有分支实际内容为空；保留旧站点，不登记输入完成。")
        if state["run"].get("schema_version") == 2:
            snapshot_path = run / "context/snapshot.json"
            snapshot, paths = gate.context_snapshot(fingerprint(snapshot_path), runs_root.resolve(),
                                                   gate.timestamp(state["run"]["started_at"], "run.started_at"), state["run"]["id"])
            artifacts += [fingerprint(path) for path in paths]
            evidence.update(context_mode=snapshot["effective_mode"], facts=len(snapshot["facts"]),
                            source_errors=snapshot["source_errors"])
        else:
            page = site.load_json(run / "todo/page.json")
            from prepare_audit import visualize_reference
            reference = visualize_reference(page)
            tasks = gate.parse_tasks((run / "todo/source.html").read_text(encoding="utf-8"))
            site.require(bool(tasks), "旧版待办任务为空；核对是否完整读取；通用模式请运行setup启用v2。")
            artifacts += [fingerprint(run / "todo/page.json"), fingerprint(run / "todo/source.html")]
            evidence.update(tasks=len(tasks), reference=reference)
    else:
        site.require(issue_path is not None, "本阶段必须提供 --issue")
        issue = site.load_json(issue_path)
        site.require(issue.get("date") == state["run"]["date"], "简报日期与运行日期不一致")
        assets = site.validate_issue(issue, assets_root)
        artifacts.append(fingerprint(issue_path))
        if phase == "editorial":
            site.require(editorial is not None and editorial.is_file() and editorial.stat().st_size > 0,
                         "必须提供非空 --editorial 统一工作稿；不能以采集状态代替完整阅读")
            artifacts.append(fingerprint(editorial))
        else:
            site.require(audit_path is not None, "本阶段必须提供 --audit")
            evidence["validation"] = gate.validate_run_audit(issue, audit_path, assets_root,
                runs_root=runs_root, require_qa=phase in ("review", "published"))
            artifacts.append(fingerprint(audit_path, "file" if phase in ("review", "published") else "audit-input"))
            artifacts += [fingerprint(path) for path in assets.values()]
            artifacts.append(fingerprint(assets_root / "asset-index.json"))
            audit = site.load_json(audit_path)
            # Include every source/evidence record referenced by the audited input.
            def referenced(value):
                if isinstance(value, dict):
                    if "path" in value and "sha256" in value:
                        artifacts.append(fingerprint(Path(value["path"])))
                    for key, child in value.items():
                        if key != "qa":
                            referenced(child)
                elif isinstance(value, list):
                    for child in value:
                        referenced(child)
            referenced(audit)
            if phase in ("preview", "review", "published"):
                candidate = Path(audit["qa"]["preview_path"]) if phase in ("review", "published") else preview_dir
                site.require(candidate is not None, "候选阶段必须提供 --preview-dir")
                manifest = site.load_json(candidate / "manifest.json")
                record = manifest["issues"].get(issue["date"])
                site.require(record is not None and site.load_json(candidate / record["json"]) == issue,
                             "候选缺少本期或与当前内容不同")
                hashes = {name: site.sha256(path.read_bytes()) for name, path in sorted(assets.items())}
                site.require(record.get("assets") == hashes, "候选图片与本期输入不同")
                artifacts.append(fingerprint(candidate, "tree"))
                for name in ("render_issue.py", "personal_renderer.py"):
                    artifacts.append(fingerprint(site.PROJECT_ROOT / "scripts" / name))
                if phase in ("review", "published"):
                    artifacts += [fingerprint(Path(row["path"])) for row in audit["qa"]["evidence"]]
                evidence["generation"] = manifest["generation"]
            if phase == "published":
                active = site.active_release(site_root)
                site.require(active is not None, "本地网站未发布")
                current_manifest = site.load_json(active / "manifest.json")
                site.require(current_manifest["generation"] == evidence["generation"], "当前网站不是已签收候选")
                artifacts.append(fingerprint(site_root / "current", "tree"))
                evidence["entry"] = str(site_root / "current/index.html")
    # A checkpoint is append-only in history; later updates invalidate dependents.
    previous = state["phases"].get(phase)
    record = {"status": "complete", "completed_at": now(), "artifacts": artifacts, "evidence": evidence}
    if previous and previous.get("artifacts") != artifacts:
        for later in PHASES[index + 1:]:
            if state["phases"].get(later, {}).get("status") == "complete":
                state["phases"][later].update(status="stale", reason="前置检查点重新绑定：" + phase)
                event(run, state, "invalidated", phase=later, changed_phase=phase)
    state["phases"][phase] = record
    event(run, state, "checkpoint", phase=phase, record=record)
    save(run, state)
    return report(run, state)


def checkpoint(run, state, phase, **options):
    try:
        return _checkpoint(run, state, phase, **options)
    except (site.ValidationError, OSError, KeyError, TypeError) as exc:
        # Retain the actual error and checkpoint history for a later agent turn.
        # An unsuccessful validation can never leave this phase marked complete.
        state["phases"].setdefault(phase, {}).update(status="failed", failed_at=now(), error=str(exc))
        for later in PHASES[PHASES.index(phase) + 1:]:
            if state["phases"].get(later, {}).get("status") == "complete":
                state["phases"][later].update(status="stale", reason="前置阶段校验失败：" + phase)
                event(run, state, "invalidated", phase=later, changed_phase=phase)
        event(run, state, "checkpoint-failed", phase=phase, error=str(exc))
        save(run, state)
        raise


def packet(run, state):
    result = report(run, state)
    result["reading_rule"] = "本包仅供恢复定位。首次编辑仍须完整读取所有正文/栏目/结尾、全部Builders和已选择的个人参考；不能以摘要代替。"
    result["inputs"] = []
    for branch, filename in (("builders", "raw.json"), ("products", "products-manifest.json")):
        path = run / branch / filename
        if path.is_file():
            result["inputs"].append({**fingerprint(path), "branch": branch, "bytes": path.stat().st_size})
    if state["run"].get("schema_version") == 2:
        source = run / "context/snapshot.json"
        if source.is_file():
            snapshot = site.load_json(source)
            result["context_snapshot"] = fingerprint(source)
            result["personalization"] = {key: snapshot[key] for key in ("mode", "effective_mode", "captured_at", "source_errors")}
            result["personalization"]["facts"] = len(snapshot["facts"])
    else:
        source = run / "todo/source.html"
        if source.is_file():
            result["saved_tasks"] = gate.parse_tasks(source.read_text(encoding="utf-8"))
            result["todo_snapshot"] = fingerprint(source)
            result["privacy_note"] = "旧版saved_tasks含个人资料，仅用于本次编辑，不对外分享。"
    result["checkpoint_artifacts"] = {phase: [row["path"] for row in value["artifacts"]]
                                      for phase, value in state["phases"].items()}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--date")
    init.add_argument("--run-id")
    init.add_argument("--timezone", default="Asia/Shanghai")
    init.add_argument("--runs-root", type=Path, default=gate.DEFAULT_RUNS_ROOT)
    for name in ("status", "collect", "checkpoint", "packet"):
        child = sub.add_parser(name)
        child.add_argument("--run-dir", type=Path, required=True)
        if name == "collect":
            child.add_argument("--package", type=Path)
        if name == "checkpoint":
            child.add_argument("--phase", choices=PHASES, required=True)
            for key in ("issue", "editorial", "audit", "preview-dir"):
                child.add_argument("--" + key, type=Path)
            child.add_argument("--assets-root", type=Path, default=site.DEFAULT_ASSETS_ROOT)
            child.add_argument("--site-root", type=Path, default=site.DEFAULT_SITE_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_run(runs_root=args.runs_root, date=args.date, run_id=args.run_id, timezone_name=args.timezone)
        else:
            run = args.run_dir.resolve()
            site.require(run.is_relative_to(gate.DEFAULT_RUNS_ROOT.resolve()), "run-dir 必须属于项目 data/runs")
            with lock(run):
                state = load(run)
                reconcile(run, state)
                save(run, state)
                if args.command == "collect":
                    result = collect(run, state, package=args.package)
                elif args.command == "checkpoint":
                    result = checkpoint(run, state, args.phase, issue_path=args.issue, editorial=args.editorial,
                        audit_path=args.audit, preview_dir=args.preview_dir, assets_root=args.assets_root, site_root=args.site_root)
                else:
                    result = packet(run, state) if args.command == "packet" else report(run, state)
    except (site.ValidationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
