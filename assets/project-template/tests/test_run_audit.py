import base64
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daily_site as site
import run_audit as gate
import prepare_audit as prepare


class RunAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "data/runs"
        self.run = self.runs / "test-run"
        self.run.mkdir(parents=True)
        self.resources = self.root / "resources"
        (self.resources / "assets").mkdir(parents=True)
        (self.resources / "vendor").mkdir()
        (self.resources / "vendor/alpine.min.js").write_text("// fixture runtime")
        self.output = self.root / "site"
        self.now = datetime.now(timezone.utc)
        self.read_at = (self.now - timedelta(minutes=10)).isoformat()
        self.started = (self.now - timedelta(minutes=20)).isoformat()
        self.issue = self.make_issue()
        self.issue_file = self.run / "issue.json"
        self.audit_file = self.run / "audit.json"
        self.raw = {"status": "ok", "x": [
            {"name": "A", "tweets": [self.tweet(1), self.tweet(2)]},
            {"name": "B", "tweets": [self.tweet(3)]}],
            "stats": {"xBuilders": 2, "totalTweets": 3}}
        self.tasks = [{"id": "t1", "title": "网站更新", "status": "doing", "next": "保留完整来源"},
                      {"id": "t2", "title": "验收流程", "status": "todo", "next": "检查发布入口"}]
        source = "<script>const tasks=" + json.dumps(self.tasks, ensure_ascii=False) + ";window.untrusted='ignored';</script>"
        source_record = self.save("todo.html", source.encode())
        todo_record = {"run_id": "test-run", "page_id": "page_fixture",
                       "reference": "visualize:task-source", "read_at": self.read_at,
                       "source_sha256": source_record["sha256"], "tasks": self.tasks}
        self.audit = {"schema_version": 1, "run": {"id": "test-run", "started_at": self.started},
                      "issue_sha256": site.sha256(site.canonical(self.issue)),
                      "builders": {"raw": self.save("builders.json", site.canonical(self.raw))},
                      "todo": {"page_id": "page_fixture", "reference": "visualize:task-source",
                               "read_at": self.read_at, "page": self.save("page.json", site.canonical({"id": "page_fixture", "body": "[看板](visualize:task-source)"})),
                               "source": source_record, "record": self.save("todo.json", site.canonical(todo_record))},
                      "personal_bindings": [{"url": "https://example.org/personal", "task_ids": ["t1"]}],
                      "media": {"products": [{"url": "https://example.org/personal", "missing": "已检查教程原文，保存的页面不含可用产品图片。", "review": self.no_image_review()}], "avatars": [
                          self.missing_avatar("A"), self.missing_avatar("B")]}}
        (self.resources / "asset-index.json").write_bytes(site.canonical({"items": {}}))
        prior = self.make_issue("2026-10-13")
        prior["builders"] = []
        self.previous = site.publish(prior, self.output, self.resources)
        self.candidate = site.publish(self.issue, self.output, self.resources, preview_root=self.run / "previews")
        self.add_qa()
        self.flush()

    def tearDown(self):
        self.tmp.cleanup()

    def tweet(self, number):
        return {"url": f"https://x.com/test/status/{number}", "createdAt": "2026-10-19T12:00:00.000Z", "text": f"原帖 {number}"}

    def make_issue(self, day="2026-10-20"):
        def builder(name, numbers):
            return {"author": name, "role": "", "one_sentence": "完整保留本期原帖", "paragraphs": ["用于门禁的隔离测试内容。"],
                    "avatar": None, "links": [{"url": self.tweet(n)["url"], "text": "原帖"} for n in numbers],
                    "publication": {"posts": [{"url": self.tweet(n)["url"], "published_at": self.tweet(n)["createdAt"]} for n in numbers]}}
        return {"schema_version": 1, "date": day, "product": {"featured": [], "quick": [], "unselected": [], "personal": [
            {"title": "内容审核教程", "label": "使用教程", "url": "https://example.org/personal", "core": "事实", "relation": "对应网站更新待办", "question": "是否保留来源？", "image": None}]},
                "builders": [builder("A", [1, 2]), builder("B", [3])], "podcast": None}

    def save(self, name, data):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": str(path), "sha256": site.sha256(data)}

    def no_image_review(self):
        return {"decision": "no_candidates", "sources": [{"url": "https://example.org/personal",
                "status": "checked", "evidence": self.save("product-source.html", b"<html>Text-only tutorial</html>")}],
                "candidates": []}

    def missing_avatar(self, author):
        return {"author": author, "missing": "已检查作者个人主页，页面未提供可核对身份的头像。",
                "review": {"sources": [{"url": "https://example.org/" + author, "status": "checked",
                    "evidence": self.save("avatar-" + author + ".html", b"<html>Author profile without photo</html>")}]}}

    def media_checks(self):
        return [{"url": item["url"], "image_path": item["image"]["path"] if item["image"] else None,
                 "rendered_count": 1 if item["image"] else 0,
                 "loaded": True if item["image"] else None}
                for category in ("featured", "personal") for item in self.issue["product"][category]]

    def with_image(self):
        path = self.resources / "assets/product.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
        self.issue["product"]["personal"][0]["image"] = {"path": "assets/product.svg", "width": 1,
            "height": 1, "kind": "screenshot", "caption": "隔离测试图"}
        review = self.no_image_review()
        review["decision"] = "selected"
        review["candidates"] = [{"url": "https://example.org/picture.svg", "decision": "selected",
            "reason": "实际查看：产品教程截图与正文对应", "evidence": self.save("candidate.json", b'{"download":"ok"}')}]
        self.audit["media"]["products"] = [{"url": "https://example.org/personal", "identity": "product:personal", "review": review}]
        cached = {"identity": "product:personal", "path": "assets/product.svg", "sha256": site.sha256(path.read_bytes()),
                  "visual_verified": True, "source_page": "https://example.org/personal", "asset_url": "https://example.org/picture.svg"}
        (self.resources / "asset-index.json").write_bytes(site.canonical({"items": {"product:personal": cached}}))
        return self.audit["media"]["products"][0]

    def add_qa(self):
        generation = self.candidate["release"]
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2mZ8AAAAASUVORK5CYII=")
        self.audit["qa"] = {"passed": True, "reviewed_at": (self.now + timedelta(seconds=10)).isoformat(),
                            "preview_path": self.candidate["preview_path"], "generation": generation,
                            "preview_sha256": gate.preview_digest(Path(self.candidate["preview_path"])),
                            "source_sha256": gate.source_hashes(self.audit),
                            "evidence": [{"kind": "ego-check", **self.save("ego.json", site.canonical({"tool": "ego-browser", "passed": True, "generation": generation, "checks": ["fixture sign-off"], "media_checks": self.media_checks()}))},
                                         {"kind": "screenshot", **self.save("screen.png", png)}]}

    def flush(self):
        self.audit["issue_sha256"] = site.sha256(site.canonical(self.issue))
        self.issue_file.write_bytes(site.canonical(self.issue))
        self.audit_file.write_bytes(site.canonical(self.audit))

    def validate(self, qa=True):
        self.flush()
        return gate.validate_run_audit(self.issue, self.audit_file, self.resources, runs_root=self.runs, require_qa=qa)

    def cli(self):
        self.flush()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
            code = site.main(["publish", str(self.issue_file), "--site-root", str(self.output), "--assets-root", str(self.resources), "--audit", str(self.audit_file)], audit_runs_root=self.runs)
        return code, error.getvalue()

    def assert_blocked(self, text):
        code, error = self.cli()
        self.assertEqual(code, 1, error)
        self.assertIn(text, error)
        self.assertEqual(site.status(self.output)["release"], self.previous["release"])

    def test_valid_audit_publishes_and_repeat_is_unchanged(self):
        result = self.validate()
        self.assertEqual(result["builders"], {"authors": 2, "posts": 3})
        self.assertEqual(self.cli()[0], 0)
        state = site.status(self.output)
        self.assertEqual(state["latest"], "2026-10-20")
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(site.status(self.output)["release"], state["release"])

    def test_removed_author_and_missing_post_are_blocked(self):
        original = copy.deepcopy(self.issue)
        self.issue["builders"].pop()
        self.assert_blocked("作者集合")
        self.issue = original
        self.issue["builders"][0]["links"].pop()
        self.issue["builders"][0]["publication"]["posts"].pop()
        self.assert_blocked("原帖集合")

    def test_same_count_different_post_and_wrong_time_are_blocked(self):
        original = copy.deepcopy(self.issue)
        self.issue["builders"][0]["links"][0]["url"] = "https://x.com/test/status/999"
        self.issue["builders"][0]["publication"]["posts"][0]["url"] = "https://x.com/test/status/999"
        self.assert_blocked("原帖集合")
        self.issue = original
        self.issue["builders"][0]["publication"]["posts"][0]["published_at"] = "2026-10-19T11:00:00Z"
        self.assert_blocked("发布时间")

    def test_raw_error_is_not_empty_success(self):
        self.raw["status"] = "error"
        self.raw["x"] = []
        self.issue["builders"] = []
        self.audit["media"]["avatars"] = []
        self.audit["builders"]["raw"] = self.save("builders.json", site.canonical(self.raw))
        self.assert_blocked("不是成功状态")

    def test_partial_with_explicit_x_success_keeps_complete_people(self):
        self.raw["status"] = "partial"
        self.raw["feedStatus"] = {"x": {"status": "ok"}, "podcasts": {"status": "error"}}
        self.audit["builders"]["raw"] = self.save("builders.json", site.canonical(self.raw))
        result = self.validate(qa=False)
        self.assertEqual(result["builders"], {"authors": 2, "posts": 3})

    def test_partial_with_failed_or_missing_x_evidence_is_blocked(self):
        self.raw["status"] = "partial"
        for state in ({"x": {"status": "error"}}, {"podcasts": {"status": "ok"}}):
            with self.subTest(feedStatus=state):
                self.raw["feedStatus"] = state
                self.audit["builders"]["raw"] = self.save("builders.json", site.canonical(self.raw))
                self.assert_blocked("X 完整成功证据")

    def test_genuinely_empty_builders_can_keep_product_issue(self):
        self.raw["x"] = []
        self.raw["stats"] = {"xBuilders": 0, "totalTweets": 0}
        self.issue["builders"] = []
        self.audit["media"]["avatars"] = []
        self.audit["builders"]["raw"] = self.save("builders.json", site.canonical(self.raw))
        self.assertEqual(self.validate(qa=False)["builders"]["posts"], 0)

    def test_wrong_task_and_stale_todo_are_blocked(self):
        self.audit["personal_bindings"][0]["task_ids"] = ["missing-id"]
        self.assert_blocked("不在当前待办")
        self.audit["personal_bindings"][0]["task_ids"] = ["t1"]
        self.audit["todo"]["read_at"] = (self.now - timedelta(days=1)).isoformat()
        self.assert_blocked("早于本次运行")

    def test_changed_or_incomplete_task_record_is_blocked(self):
        record = site.load_json(Path(self.audit["todo"]["record"]["path"]))
        record["tasks"].pop()
        self.audit["todo"]["record"] = self.save("todo.json", site.canonical(record))
        self.assert_blocked("提取内容不完整")

    def test_wrong_todo_page_reference_is_blocked(self):
        self.audit["todo"]["page"] = self.save("page.json", site.canonical({"id": "page_fixture", "body": "visualize:older-file"}))
        self.assert_blocked("没有引用")

    def test_product_identity_and_digest_are_required(self):
        path = self.resources / "assets/product.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
        self.issue["product"]["personal"][0]["image"] = {"path": "assets/product.svg", "width": 1, "height": 1, "kind": "screenshot", "caption": "隔离测试图"}
        self.audit["media"]["products"] = [{"url": "https://example.org/personal", "identity": "product:personal"}]
        record = {"identity": "product:personal", "path": "assets/wrong.svg", "sha256": site.sha256(path.read_bytes()), "visual_verified": True, "source_page": "https://example.org/personal"}
        index = {"items": {"product:personal": record}}
        (self.resources / "asset-index.json").write_bytes(site.canonical(index))
        self.assert_blocked("身份或路径错绑")
        record["path"] = "assets/product.svg"
        record["sha256"] = "0" * 64
        (self.resources / "asset-index.json").write_bytes(site.canonical(index))
        self.assert_blocked("缓存摘要不一致")

    def test_unbound_or_wrong_avatar_is_blocked(self):
        path = self.resources / "assets/avatar.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
        self.issue["builders"][0]["avatar"] = "assets/avatar.svg"
        self.audit["media"]["avatars"] = [{"author": "B", "missing": "测试"}]
        index = {"items": {"avatar:A": {"identity": "avatar:B", "path": "assets/avatar.svg", "sha256": site.sha256(path.read_bytes()), "visual_verified": True, "source_page": "https://example.org/B"}}}
        (self.resources / "asset-index.json").write_bytes(site.canonical(index))
        self.assert_blocked("身份或路径错绑")
        index["items"]["avatar:A"]["identity"] = "avatar:A"
        index["items"]["avatar:A"]["visual_verified"] = False
        (self.resources / "asset-index.json").write_bytes(site.canonical(index))
        self.assert_blocked("尚未视觉核对")

    def test_missing_or_stale_qa_and_changed_candidate_are_blocked(self):
        original = copy.deepcopy(self.audit["qa"])
        del self.audit["qa"]
        self.assert_blocked("audit.qa")
        self.audit["qa"] = copy.deepcopy(original)
        self.audit["qa"]["generation"] = "0" * 24
        self.assert_blocked("候选版本不一致")
        self.audit["qa"] = original
        (Path(self.candidate["preview_path"]) / "index.html").write_text("changed after review")
        self.assert_blocked("候选文件已改变")

    def test_changed_issue_after_candidate_is_blocked(self):
        self.issue["product"]["personal"][0]["relation"] = "验收后改动"
        self.assert_blocked("简报内容已改变")

    def test_changed_source_after_review_and_missing_evidence_are_blocked(self):
        self.raw["generatedAt"] = self.now.isoformat()
        self.audit["builders"]["raw"] = self.save("builders.json", site.canonical(self.raw))
        self.assert_blocked("来源摘要")
        self.audit["qa"]["source_sha256"]["builders"] = self.audit["builders"]["raw"]["sha256"]
        self.audit["qa"]["evidence"] = self.audit["qa"]["evidence"][:1]
        self.assert_blocked("实际截图")

    def test_audit_and_sources_cannot_escape_run_root(self):
        outside = self.root / "outside.json"
        outside.write_bytes(site.canonical(self.raw))
        self.audit["builders"]["raw"] = {"path": str(outside), "sha256": site.sha256(outside.read_bytes())}
        self.assert_blocked("data/runs")
        with self.assertRaises(site.ValidationError):
            gate.parse_tasks("const tasks=fetch('https://example.org');")
        with self.assertRaises(site.ValidationError):
            gate.parse_tasks('const tasks=[{"id":"a"}]+steal();')

    def test_cli_requires_audit_and_validate_can_check_without_qa(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_result:
                site.main(["publish", str(self.issue_file)])
        self.assertEqual(exit_result.exception.code, 2)
        del self.audit["qa"]
        self.flush()
        with contextlib.redirect_stdout(io.StringIO()):
            code = site.main(["validate", str(self.issue_file), "--assets-root", str(self.resources), "--audit", str(self.audit_file)], audit_runs_root=self.runs)
        self.assertEqual(code, 0)
        self.assertEqual(site.status(self.output)["release"], self.previous["release"])


    def test_missing_image_requires_review_and_concrete_reason(self):
        binding = self.audit["media"]["products"][0]
        original = binding.pop("review")
        self.assert_blocked("产品取图 review")
        binding["review"] = original
        binding["missing"] = "未获取到图片"
        self.assert_blocked("统一占位说明")

    def test_image_search_must_check_original_and_unavailable_needs_alternate(self):
        review = self.audit["media"]["products"][0]["review"]
        review["sources"][0]["url"] = "https://example.org/newsletter"
        self.assert_blocked("必须逐条检查原文")
        review["sources"][0]["url"] = "https://example.org/personal"
        review["sources"][0]["status"] = "unavailable"
        self.assert_blocked("替代来源")

    def test_selected_candidate_must_match_cache_identity(self):
        binding = self.with_image()
        self.assertEqual(self.validate(qa=False)["status"], "audited")
        binding["review"]["candidates"][0]["url"] = "https://example.org/wrong.svg"
        self.assert_blocked("候选图 URL 与素材身份缓存不一致")

    def test_candidate_and_source_evidence_tampering_are_blocked(self):
        for category in ("sources", "candidates"):
            with self.subTest(category=category):
                binding = self.with_image()
                evidence = binding["review"][category][0]["evidence"]
                Path(evidence["path"]).write_text("changed after provenance capture")
                self.assert_blocked("采集记录摘要不一致")

    def test_missing_image_classifications_require_actual_attempts(self):
        review = self.audit["media"]["products"][0]["review"]
        for decision in ("all_rejected", "download_failed"):
            review["decision"] = decision
            self.assert_blocked("必须")
        review["decision"] = "no_candidates"
        review["candidates"] = [{"url": "https://example.org/pic.png", "decision": "rejected",
             "reason": "图片是作者头像，与教程无关", "evidence": self.save("rejected.json", b'{"reason":"avatar"}')}]
        self.assert_blocked("no_candidates")
        review["decision"] = "all_rejected"
        self.assertEqual(self.validate(qa=False)["status"], "audited")
        review["decision"] = "download_failed"
        self.assert_blocked("实际下载失败证据")
        review["candidates"][0]["decision"] = "download_failed"
        self.assertEqual(self.validate(qa=False)["status"], "audited")

    def test_qa_image_coverage_missing_extra_and_unloaded_are_blocked(self):
        for rows, message in (([], "图片覆盖遗漏"),
                (self.media_checks() + [{"url": "https://example.org/extra"}], "多余条目"),
                ([{"url": "https://example.org/personal", "image_path": None, "rendered_count": 1, "loaded": None}], "展示数量")):
            with self.subTest(rows=rows):
                check = {"tool": "ego-browser", "passed": True, "generation": self.candidate["release"], "media_checks": rows}
                self.audit["qa"]["evidence"][0] = {"kind": "ego-check", **self.save("ego.json", site.canonical(check))}
                self.assert_blocked(message)
        self.with_image()
        rows = self.media_checks()
        rows[0]["loaded"] = False
        with self.assertRaisesRegex(site.ValidationError, "未成功加载"):
            gate.validate_media_checks(self.issue, {"media_checks": rows})
        rows[0]["loaded"] = True
        rows[0]["image_path"] = "assets/wrong.svg"
        with self.assertRaisesRegex(site.ValidationError, "图片路径"):
            gate.validate_media_checks(self.issue, {"media_checks": rows})

    def test_media_decisions_are_bound_to_qa(self):
        self.audit["media"]["products"][0]["missing"] = "重新检查页面确认只有文字，缺少相关截图与产品图。"
        self.assert_blocked("来源摘要")

    def test_prepare_computes_review_evidence_hashes(self):
        self.flush()
        (self.run / "run.json").write_bytes(site.canonical({"id": "test-run", "date": self.issue["date"], "started_at": self.started}))
        products = copy.deepcopy(self.audit["media"]["products"])
        row = products[0]["review"]["sources"][0]
        record = row.pop("evidence")
        row["evidence_path"] = record["path"]
        row["evidence"] = {"path": "/untrusted", "sha256": "0" * 64}
        bindings = {"products": products, "personal_bindings": self.audit["personal_bindings"],
                    "missing_avatars": copy.deepcopy(self.audit["media"]["avatars"])}
        for avatar in bindings["missing_avatars"]:
            source = avatar["review"]["sources"][0]
            source["evidence_path"] = source.pop("evidence")["path"]
        bindings_path = self.run / "bindings.json"
        bindings_path.write_bytes(site.canonical(bindings))
        result = prepare.create_audit(issue_path=self.issue_file, run_dir=self.run,
            builders_raw=Path(self.audit["builders"]["raw"]["path"]), todo_page=Path(self.audit["todo"]["page"]["path"]),
            todo_source=Path(self.audit["todo"]["source"]["path"]), bindings_path=bindings_path,
            output=self.run / "prepared.json", assets_root=self.resources, runs_root=self.runs)
        self.assertEqual(result["status"], "prepared")
        actual = site.load_json(self.run / "prepared.json")["media"]["products"][0]["review"]["sources"][0]
        self.assertEqual(actual["evidence"], {**record, "path": str(Path(record["path"]).resolve())})
        self.assertNotIn("evidence_path", actual)


    def test_missing_avatar_needs_actual_source_checks(self):
        binding = self.audit["media"]["avatars"][0]
        review = binding.pop("review")
        self.assert_blocked("缺失头像 review")
        binding["review"] = review
        original_reason = binding["missing"]
        binding["missing"] = "缓存没有头像"
        self.assert_blocked("缓存未命中")
        binding["missing"] = original_reason
        sources = review["sources"]
        review["sources"] = []
        self.assert_blocked("必须实际检查作者")
        review["sources"] = sources
        Path(sources[0]["evidence"]["path"]).write_text("modified profile")
        self.assert_blocked("采集记录摘要不一致")


if __name__ == "__main__":
    unittest.main()
